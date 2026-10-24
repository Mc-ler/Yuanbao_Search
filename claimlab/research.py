"""Scoped live research: requirement decomposition → queries → A/B/B-C sources.

Shared by the HTTP research endpoint and the CLI live validator. It performs
real SearchPro calls through the current API-only gateway.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

from .contracts import ResearchTask, SearchBatch, SearchPage
from .demos import match_demo
from .logging import event
from .skills.answer import build_answer
from .skills.grading import grade_page
from .skills.research_report import build_research_report
from .skills.query import (
    build_queries_llm,
    plan_fallback_queries,
    plan_key,
    plan_requery_queries,
    plan_requirement_queries,
)
from .skills.requirements import decompose_requirements
from .skills.source_policy import is_relevant, source_tier

logger = logging.getLogger("claimlab.research")


def _grades(pages: list[SearchPage], field: str | None) -> dict[str, int]:
    counts = {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0}
    for page in pages:
        counts[grade_page(page, field=field).grade] += 1
    return counts


async def run_research(
    sandbox: Any,
    task: ResearchTask,
    *,
    example_id: str = "",
    run_id: str | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    demo = match_demo(task.text, example_id)
    if demo is not None:
        return demo

    gateway = sandbox.new_gateway()
    run_id = run_id or f"research-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6]}"
    plan = await decompose_requirements(sandbox.llm, task)
    rows: list[dict[str, Any]] = []
    all_queries = []
    all_fallbacks = []
    all_requeries = []
    for requirement in plan.requirements:
        used: set[tuple[str, str | None, str | None]] = set()
        executed: list[dict[str, Any]] = []
        pages: list[SearchPage] = []

        initial = [
            plan
            for plan in (await build_queries_llm(sandbox.llm, requirement))
            if plan_key(plan) not in used
        ]
        if not initial:
            initial = plan_requirement_queries(
                requirement,
                used=used,
            )
        initial = initial[:2]
        all_queries.extend(initial)
        for item in initial:
            batch: SearchBatch = await gateway.search(
                run_id,
                requirement.requirement_id,
                item,
                use_cache=not refresh,
            )
            used.add(plan_key(item))
            pages.extend(batch.pages)
            executed.append(
                {
                    "query": item.query,
                    "strategy": item.strategy,
                    "pages": len(batch.pages),
                    "error": batch.error,
                    "cache_hit": batch.cache_hit,
                }
            )

        tier = source_tier(pages, requirement=requirement)
        # Relaxed policy: accept B/C as a terminal tier; only escalate when we
        # have no usable source at all.
        if tier == "insufficient":
            fallback = plan_fallback_queries(
                requirement,
                used=used,
            )[:1]
            all_fallbacks.extend(fallback)
            for item in fallback:
                batch = await gateway.search(
                    run_id,
                    requirement.requirement_id,
                    item,
                    use_cache=not refresh,
                )
                used.add(plan_key(item))
                pages.extend(batch.pages)
                executed.append(
                    {
                        "query": item.query,
                        "strategy": item.strategy,
                        "pages": len(batch.pages),
                        "error": batch.error,
                    }
                )
            tier = source_tier(pages, requirement=requirement)

        if tier == "insufficient":
            requery = plan_requery_queries(
                requirement,
                used=used,
            )[:1]
            all_requeries.extend(requery)
            for item in requery:
                batch = await gateway.search(
                    run_id,
                    requirement.requirement_id,
                    item,
                    use_cache=not refresh,
                )
                used.add(plan_key(item))
                pages.extend(batch.pages)
                executed.append(
                    {
                        "query": item.query,
                        "strategy": item.strategy,
                        "pages": len(batch.pages),
                        "error": batch.error,
                    }
                )
            tier = source_tier(pages, requirement=requirement)

        relevant_pages = [page for page in pages if is_relevant(page, requirement)]
        counts = _grades(pages, requirement.field)
        relevant_counts = _grades(relevant_pages, requirement.field)
        top = [
            {
                "grade": grade_page(page, field=requirement.field).grade,
                "domain": page.domain,
                "title": page.title,
                "url": page.url,
                "date": page.date,
            }
            for page in relevant_pages
            if grade_page(page, field=requirement.field).grade in {"A", "B", "C"}
        ][:6]
        rows.append(
            {
                "requirement_id": requirement.requirement_id,
                "field": requirement.field,
                "text": requirement.text,
                "tier": tier,
                "pages": len(pages),
                "relevant_pages": len(relevant_pages),
                "grades": counts,
                "relevant_grades": relevant_counts,
                "executed": executed,
                "top_sources": top,
            }
        )
        event(
            logger,
            "research.requirement",
            example_id=example_id,
            field=requirement.field,
            tier=tier,
            pages=len(pages),
            relevant=len(relevant_pages),
            official=relevant_counts["A"] + relevant_counts["B"],
            queries=len(executed),
        )

    total_pages = sum(row["pages"] for row in rows)
    relevant_pages = sum(row["relevant_pages"] for row in rows)
    ab_pages = sum(row["grades"]["A"] + row["grades"]["B"] for row in rows)
    relevant_ab = sum(row["relevant_grades"]["A"] + row["relevant_grades"]["B"] for row in rows)
    covered = sum(1 for row in rows if row["tier"] == "A/B")
    covered_relaxed = sum(1 for row in rows if row["tier"] in {"A/B", "B/C"})
    distinct = {row["field"] for row in rows}
    distinct_covered = {row["field"] for row in rows if row["tier"] == "A/B"}
    metrics = {
        "fields": len(rows),
        "fields_with_ab": covered,
        "fields_covered": covered_relaxed,
        "field_coverage": covered / len(rows) if rows else 0.0,
        "distinct_fields": len(distinct),
        "distinct_fields_with_ab": len(distinct_covered),
        "distinct_field_coverage": len(distinct_covered) / len(distinct) if distinct else 0.0,
        "pages": total_pages,
        "relevant_pages": relevant_pages,
        "ab_pages": ab_pages,
        "relevant_ab_pages": relevant_ab,
        "official_page_rate": ab_pages / total_pages if total_pages else 0.0,
        "relevant_official_rate": relevant_ab / relevant_pages if relevant_pages else 0.0,
        "zero_requirements": sum(1 for row in rows if row["pages"] == 0),
        "cache_hits": sum(
            1
            for row in rows
            for item in row["executed"]
            if item.get("cache_hit")
        ),
    }
    event(logger, "research.done", example_id=example_id, **metrics)

    store = getattr(sandbox, "store", None)
    if store is not None:
        sources = []
        for row in rows:
            for src in row.get("top_sources") or []:
                sources.append({"field": row.get("field"), **src})
        try:
            store.upsert_run(
                run_id,
                mode="research_topic",
                question=task.text,
                subject=task.subject,
                city=task.city,
                domain=plan.domain,
                method=plan.method,
                metrics=metrics,
                result=rows,
            )
            store.upsert_sources(run_id, sources)
        except Exception:
            pass

    answer = await build_answer(sandbox.llm, task.text, rows)
    report = build_research_report(task.text, rows, answer, metrics)
    return {
        "run_id": run_id,
        "example_id": example_id or None,
        "domain": plan.domain,
        "method": plan.method,
        "question": task.text,
        "requirements": plan.requirements,
        "queries": all_queries,
        "fallback_queries": all_fallbacks,
        "requery_queries": all_requeries,
        "results": rows,
        "metrics": metrics,
        "answer": answer,
        "report": report,
    }
