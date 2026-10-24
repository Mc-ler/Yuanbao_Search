"""Deep research: requirements -> expanded queries -> deduped sources -> report.

The deep board deliberately does not produce R1-R5 verdicts. It retrieves,
dedupes, grades, organizes a source ledger, attaches best-effort page
screenshots, and asks the LLM for a cited research summary. The claim board
(claimlab.pipeline) keeps the deterministic R1-R5 judgment.

Results are not persisted: no SQLite rows, no files, screenshots only in memory.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

from .contracts import Requirement, SearchBatch, SearchPage
from .logging import event
from .planning import ResearchPlan, build_research_plan
from .skills.answer import build_answer, build_citations
from .skills.content import best_excerpt, content_chars
from .skills.dedup import cluster_pages, page_key
from .skills.grading import grade_page
from .skills.research_report import build_research_report
from .skills.source_policy import is_relevant, source_tier

logger = logging.getLogger("claimlab.research")


def _grade_counts(pages: list[SearchPage], field: str | None) -> dict[str, int]:
    counts = {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0}
    for page in pages:
        counts[grade_page(page, field=field).grade] += 1
    return counts


def _rank(page: SearchPage, field: str) -> tuple:
    grade = grade_page(page, field=field)
    order = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
    return (order.get(grade.grade, 9), -(page.score or 0.0), page.date or "")


def _top_sources(
    pages: list[SearchPage],
    requirement: Requirement,
    page_cluster: dict[str, str],
    limit: int = 6,
) -> list[dict[str, Any]]:
    representatives: dict[str, SearchPage] = {}
    for page in pages:
        key = page_key(page)
        cluster = page_cluster.get(key) or key
        current = representatives.get(cluster)
        if current is None or _rank(page, requirement.field) < _rank(current, requirement.field):
            representatives[cluster] = page
    ordered = sorted(representatives.values(), key=lambda page: _rank(page, requirement.field))
    result = []
    for page in ordered[:limit]:
        key = page_key(page)
        cluster = page_cluster.get(key) or key
        grade = grade_page(page, field=requirement.field)
        if grade.grade not in {"A", "B", "C"}:
            continue
        result.append(
            {
                "grade": grade.grade,
                "domain": page.domain,
                "title": page.title,
                "url": page.url,
                "date": page.date,
                "passage": page.passage,
                "excerpt": best_excerpt(page, requirement.search_terms),
                "content_excerpt": best_excerpt(page, requirement.search_terms) if page.content else "",
                "content_chars": content_chars(page),
                "cluster_id": cluster,
                "cluster_size": sum(
                    1 for item in pages
                    if (page_cluster.get(page_key(item)) or page_key(item)) == cluster
                ),
                "cluster_domains": sorted(
                    {
                        item.domain
                        for item in pages
                        if (page_cluster.get(page_key(item)) or page_key(item)) == cluster and item.domain
                    }
                ),
            }
        )
    return result


async def _execute_queries(
    gateway: Any,
    run_id: str,
    requirement: Requirement,
    plans: list[Any],
    refresh: bool,
    collected: list[tuple[SearchPage, str, str]],
    executed: list[dict[str, Any]],
) -> list[SearchPage]:
    pages: list[SearchPage] = []
    for plan in plans:
        batch: SearchBatch = await gateway.search(
            run_id,
            requirement.requirement_id,
            plan,
            use_cache=not refresh,
        )
        pages.extend(batch.pages)
        for page in batch.pages:
            collected.append((page, requirement.requirement_id, plan.query))
        executed.append(
            {
                "query": plan.query,
                "strategy": plan.strategy,
                "site": plan.site,
                "industry": plan.industry,
                "freshness": plan.freshness,
                "pages": len(batch.pages),
                "error": batch.error,
                "cache_hit": batch.cache_hit,
            }
        )
    return pages


async def run_research(
    sandbox: Any,
    text: str,
    *,
    plan: ResearchPlan | None = None,
    refresh: bool = False,
    run_id: str | None = None,
) -> dict[str, Any]:
    gateway = sandbox.new_gateway(budget=sandbox.new_budget(profile="research"))
    run_id = run_id or f"research-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6]}"
    settings = sandbox.settings
    plan = plan or await build_research_plan(
        sandbox.llm,
        text,
        max_initial=settings.research_queries_per_requirement,
        results_per_query=settings.research_results_per_query,
    )
    collected: list[tuple[SearchPage, str, str]] = []
    rows: list[dict[str, Any]] = []
    all_queries = []
    all_fallbacks = []

    for item in plan.items:
        requirement = item.requirement
        executed: list[dict[str, Any]] = []
        remaining = max(0, settings.research_max_queries_per_run - len(all_queries))
        initial = item.queries[:remaining]
        pages = await _execute_queries(
            gateway, run_id, requirement, initial, refresh, collected, executed
        )
        all_queries.extend(initial)
        tier = source_tier(pages, requirement=requirement)
        if tier != "A/B" and settings.research_requery_rounds > 0:
            remaining = max(0, settings.research_max_queries_per_run - len(all_queries))
            extra = [*item.fallbacks, *item.requeries][: min(2, remaining)]
            if extra:
                all_fallbacks.extend(extra)
                pages.extend(
                    await _execute_queries(
                        gateway, run_id, requirement, extra, refresh, collected, executed
                    )
                )
                all_queries.extend(extra)
                tier = source_tier(pages, requirement=requirement)
        rows.append(
            {
                "requirement_id": requirement.requirement_id,
                "field": requirement.field,
                "text": requirement.text,
                "focus": requirement.focus,
                "tier": tier,
                "pages": len(pages),
                "executed": executed,
            }
        )
        event(
            logger,
            "research.requirement",
            field=requirement.field,
            tier=tier,
            pages=len(pages),
            queries=len(executed),
        )

    raw_pages = [page for page, _req, _query in collected]
    dedup_result = cluster_pages(raw_pages, sandbox.settings.dedup_threshold)
    unique_pages = dedup_result.unique_pages
    page_cluster = dedup_result.page_cluster

    ledger: list[dict[str, Any]] = []
    relevant_fields: dict[str, list[str]] = {}
    page_by_key = {page_key(page): page for page in unique_pages}
    for row, item in zip(rows, plan.items):
        requirement = item.requirement
        relevant = [page for page in unique_pages if is_relevant(page, requirement)]
        for page in relevant:
            relevant_fields.setdefault(page_key(page), []).append(requirement.field)
        counts = _grade_counts(relevant, requirement.field)
        tier = source_tier(relevant, requirement=requirement)
        top = _top_sources(relevant, requirement, page_cluster)
        row.update(
            {
                "tier": tier,
                "relevant_pages": len(relevant),
                "grades": counts,
                "relevant_grades": counts,
                "top_sources": top,
            }
        )
        ledger.append(
            {
                "requirement_id": requirement.requirement_id,
                "field": requirement.field,
                "text": requirement.text,
                "focus": requirement.focus,
                "tier": tier,
                "grade_counts": counts,
                "unique_pages": len(relevant),
                "clusters": len({page_cluster.get(page_key(page)) for page in relevant}),
                "sources": top,
                "executed": row.get("executed") or [],
            }
        )
        event(
            logger,
            "research.ledger",
            field=requirement.field,
            tier=tier,
            unique=len(relevant),
            ab=counts["A"] + counts["B"],
        )

    # A page relevant to several requirements is counted once globally; use
    # its best field-specific grade so rates can never exceed 100%.
    rank = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
    grade_totals = {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0}
    for key, fields in relevant_fields.items():
        page = page_by_key.get(key)
        if page is None:
            continue
        grades = [grade_page(page, field=field) for field in fields]
        best = min(grades, key=lambda item: rank.get(item.grade, 9))
        grade_totals[best.grade] += 1

    citations = build_citations(ledger)
    number_by_url = {c["url"]: c["n"] for c in citations}
    for entry in ledger:
        for source in entry["sources"]:
            source["n"] = number_by_url.get(source.get("url"))

    screenshot_sources = [
        {"n": c["n"], "url": c["url"], "passage": c.get("passage") or ""}
        for c in citations[: sandbox.settings.screenshot_max]
    ]
    shots = await sandbox.screenshots.capture_many(screenshot_sources)
    screenshot_meta: dict[int, dict[str, Any]] = {}
    images: list[dict[str, Any]] = []
    for number, shot in shots.items():
        if shot.error:
            screenshot_meta[number] = {"url": None, "captured": False, "error": shot.error}
            continue
        sandbox.evidence_images.put(run_id, number, shot.data, shot.media_type)
        screenshot_meta[number] = {
            "url": f"/api/evidence/{run_id}/{number}",
            "captured": True,
            "error": None,
        }
        images.append(
            {
                "n": number,
                "data_url": f"data:{shot.media_type};base64,{base64.b64encode(shot.data).decode('ascii')}",
            }
        )

    for entry in ledger:
        for source in entry["sources"]:
            meta = screenshot_meta.get(int(source.get("n") or 0))
            if meta is not None:
                source["screenshot_url"] = meta.get("url")
                source["screenshot_error"] = meta.get("error")

    answer = await build_answer(
        sandbox.llm,
        text,
        ledger,
        images=images or None,
        screenshots=screenshot_meta,
    )

    total_queries = sum(len(row["executed"]) for row in rows)
    directed = sum(
        1
        for row in rows
        for item in row["executed"]
        if item.get("site") or item.get("industry")
    )
    relevant_total = len(relevant_fields)
    requery_calls = sum(
        1
        for row in rows
        for item in row.get("executed", [])
        if item.get("strategy") in {"B/C降级", "再查询"}
    )
    metrics = {
        "metrics_version": 3,
        "requirements": len(rows),
        "queries": total_queries,
        "queries_per_requirement": total_queries / len(rows) if rows else 0.0,
        "requery_calls": requery_calls,
        "content_pages": sum(1 for page in unique_pages if page.content),
        "content_chars": sum(len(page.content or "") for page in unique_pages),
        "sources_with_excerpt": sum(
            1
            for row in ledger
            for source in row.get("sources", [])
            if source.get("excerpt")
        ),
        "independent_domains": len({page.domain for page in unique_pages if page.domain}),
        "counter_queries": sum(
            1
            for plan in all_queries
            if any(marker in plan.query for marker in ("反驳", "争议", "辟谣", "不同说法"))
        ),
        "directed_queries": directed,
        "total_queries": total_queries,
        "directed_query_rate": directed / total_queries if total_queries else 0.0,
        "pages_raw": len(raw_pages),
        "pages_unique": len(unique_pages),
        "duplicates_removed": max(0, len(raw_pages) - len(unique_pages)),
        "clusters": len(dedup_result.clusters),
        "relevant_unique": relevant_total,
        "grade_counts": grade_totals,
        "a_source_rate": grade_totals["A"] / relevant_total if relevant_total else 0.0,
        "ab_source_rate": (grade_totals["A"] + grade_totals["B"]) / relevant_total if relevant_total else 0.0,
        "c_source_rate": grade_totals["C"] / relevant_total if relevant_total else 0.0,
        "requirements_with_ab": sum(1 for row in rows if row["tier"] == "A/B"),
        "requirements_covered": sum(1 for row in rows if row["tier"] in {"A/B", "B/C"}),
        "zero_requirements": sum(1 for row in rows if row["pages"] == 0),
        "cache_hits": sum(
            1
            for row in rows
            for item in row["executed"]
            if item.get("cache_hit")
        ),
        "screenshots": len(images),
        "stop_reason": gateway.budget.stop_reason or "completed",
    }
    event(logger, "research.done", **metrics)

    gaps = [
        {
            "requirement_id": row["requirement_id"],
            "field": row["field"],
            "tier": row["tier"],
            "text": row["text"],
        }
        for row in rows
        if row["tier"] == "insufficient"
    ]
    report = build_research_report(text, ledger, answer, metrics, gaps=gaps)
    return {
        "run_id": run_id,
        "plan_id": plan.plan_id,
        "plan_reused": True,
        "mode": "deep",
        "domain": plan.domain,
        "method": plan.method,
        "question": text,
        "requirements": plan.items,
        "queries": all_queries,
        "fallback_queries": all_fallbacks,
        "source_ledger": ledger,
        "results": ledger,
        "metrics": metrics,
        "answer": answer,
        "report": report,
        "citation_issues": answer.get("citation_issues") or [],
        "screenshots": answer.get("screenshots") or [],
        "budget": gateway.budget.summary(),
        "stop_reason": metrics["stop_reason"],
    }
