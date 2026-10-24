"""Live, budgeted validation of the three scoped examples.

Flow per requirement:
1. run two initial QueryPlans (A/B-directed)
2. if no A/B, run one B/C fallback
3. if still none, run one requery
4. stop at four calls per requirement; never duplicate a query

This is the execution bridge between /api/plan and source-quality metrics.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from claimlab.config import load_settings  # noqa: E402
from claimlab.contracts import ResearchTask, SearchPage, jsonable  # noqa: E402
from claimlab.llm.client import build_llm  # noqa: E402
from claimlab.logging import configure_logging, event  # noqa: E402
from claimlab.runtime import build_sandbox  # noqa: E402
from claimlab.skills.grading import grade_page  # noqa: E402
from claimlab.skills.query import (  # noqa: E402
    plan_fallback_queries,
    plan_key,
    plan_requery_queries,
    plan_requirement_queries,
)
from claimlab.skills.requirements import decompose_requirements  # noqa: E402
from claimlab.skills.source_policy import is_relevant, source_tier  # noqa: E402

live_log = logging.getLogger("claimlab.live")


def load_example(value: str) -> tuple[Path, dict]:
    path = Path(value)
    if not path.exists():
        path = ROOT / "examples" / f"{value}.json"
    if not path.exists():
        raise FileNotFoundError(f"example not found: {value}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"example is not a JSON object: {path}")
    return path, data


def grade_pages(pages: list[SearchPage], field: str | None = None) -> dict[str, int]:
    counts = {"A": 0, "B": 0, "C": 0, "D": 0, "E": 0}
    for page in pages:
        counts[grade_page(page, field=field).grade] += 1
    return counts


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="Live source validation for examples")
    parser.add_argument("--example", required=True)
    parser.add_argument("--subject")
    parser.add_argument("--city")
    parser.add_argument("--heuristic", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    path, example = load_example(args.example)
    question = str(example.get("question") or "").strip()
    if not question:
        print(f"question is empty in {path}")
        return 2
    settings = load_settings()
    if not settings.search_key_present:
        print("SEARCH_API_KEY missing")
        return 2
    example_id = str(example.get("example_id") or path.stem)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = configure_logging(
        settings.logs_dir,
        f"example-live-{example_id}-{stamp}.log",
        level=settings.log_level,
        max_bytes=settings.log_max_bytes,
        backup_count=settings.log_backup_count,
    )
    subject = (args.subject or str(example.get("subject") or "")).strip() or None
    city = (args.city or str(example.get("city") or "")).strip() or None
    task = ResearchTask(
        text=question,
        mode="research_topic",
        subject=subject,
        city=city,
        constraints={
            "domain": example.get("domain") or "",
            "expected_sources": example.get("expected_sources") or [],
            "query_fields": example.get("query_fields") or [],
        },
    )
    llm = None if args.heuristic else build_llm(settings)
    sandbox = build_sandbox(settings)
    gateway = sandbox.new_gateway()
    run_id = f"live-{stamp}"
    rows: list[dict] = []
    try:
        plan = await decompose_requirements(llm, task)
        for requirement in plan.requirements:
            used: set[tuple[str, str | None, str | None]] = set()
            executed: list[dict] = []
            pages: list[SearchPage] = []
            initial = plan_requirement_queries(
                requirement, subject=subject, city=city, used=used
            )[:2]
            for item in initial:
                batch = await gateway.search(run_id, requirement.requirement_id, item)
                used.add(plan_key(item))
                pages.extend(batch.pages)
                executed.append(
                    {"query": item.query, "strategy": item.strategy, "pages": len(batch.pages), "error": batch.error}
                )
            tier = source_tier(pages, requirement=requirement)
            if tier != "A/B":
                fallback = plan_fallback_queries(
                    requirement, subject=subject, city=city, used=used
                )[:1]
                for item in fallback:
                    batch = await gateway.search(run_id, requirement.requirement_id, item)
                    used.add(plan_key(item))
                    pages.extend(batch.pages)
                    executed.append(
                        {"query": item.query, "strategy": item.strategy, "pages": len(batch.pages), "error": batch.error}
                    )
                tier = source_tier(pages, requirement=requirement)
            if tier == "insufficient":
                requery = plan_requery_queries(
                    requirement, subject=subject, city=city, used=used
                )[:1]
                for item in requery:
                    batch = await gateway.search(run_id, requirement.requirement_id, item)
                    used.add(plan_key(item))
                    pages.extend(batch.pages)
                    executed.append(
                        {"query": item.query, "strategy": item.strategy, "pages": len(batch.pages), "error": batch.error}
                    )
                tier = source_tier(pages, requirement=requirement)
            counts = grade_pages(pages, requirement.field)
            relevant_pages = [page for page in pages if is_relevant(page, requirement)]
            relevant_counts = grade_pages(relevant_pages, requirement.field)
            top = [
                {
                    "grade": grade_page(page, field=requirement.field).grade,
                    "domain": page.domain,
                    "title": page.title,
                    "url": page.url,
                }
                for page in relevant_pages
                if grade_page(page, field=requirement.field).grade in {"A", "B", "C"}
            ][:4]
            rows.append(
                {
                    "requirement_id": requirement.requirement_id,
                    "field": requirement.field,
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
                live_log,
                "live.requirement",
                example_id=example_id,
                field=requirement.field,
                tier=tier,
                pages=len(pages),
                relevant=len(relevant_pages),
                official=relevant_counts["A"] + relevant_counts["B"],
                c=relevant_counts["C"],
                queries=len(executed),
            )
    finally:
        if llm is not None:
            await llm.close()
        await sandbox.close()

    total_pages = sum(row["pages"] for row in rows)
    relevant_pages = sum(row["relevant_pages"] for row in rows)
    ab_pages = sum(row["grades"]["A"] + row["grades"]["B"] for row in rows)
    relevant_ab = sum(row["relevant_grades"]["A"] + row["relevant_grades"]["B"] for row in rows)
    fields = len(rows)
    covered = sum(1 for row in rows if row["tier"] == "A/B")
    distinct_fields = {row["field"] for row in rows}
    distinct_covered = {row["field"] for row in rows if row["tier"] == "A/B"}
    payload = {
        "example_id": example_id,
        "run_id": run_id,
        "question": question,
        "method": plan.method,
        "metrics": {
            "fields": fields,
            "fields_with_ab": covered,
            "field_coverage": covered / fields if fields else 0.0,
            "distinct_fields": len(distinct_fields),
            "distinct_fields_with_ab": len(distinct_covered),
            "distinct_field_coverage": len(distinct_covered) / len(distinct_fields) if distinct_fields else 0.0,
            "pages": total_pages,
            "relevant_pages": relevant_pages,
            "ab_pages": ab_pages,
            "relevant_ab_pages": relevant_ab,
            "official_page_rate": ab_pages / total_pages if total_pages else 0.0,
            "relevant_official_rate": relevant_ab / relevant_pages if relevant_pages else 0.0,
            "zero_requirements": sum(1 for row in rows if row["pages"] == 0),
        },
        "requirements": rows,
        "log": str(log_path),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"{example_id}: {json.dumps(payload['metrics'], ensure_ascii=False)}")
        for row in rows:
            print(f"\n[{row['field']}] tier={row['tier']} pages={row['pages']} grades={row['grades']}")
            for query in row["executed"]:
                print(f"  - {query['strategy']}: {query['query']} ({query['pages']} pages)")
            for source in row["top_sources"]:
                print(f"    {source['grade']} [{source['domain']}] {source['title'][:70]}")
    event(live_log, "live.done", example_id=example_id, **payload["metrics"])
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
