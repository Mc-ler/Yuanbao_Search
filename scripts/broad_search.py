"""Broad search: sweep Freshness windows / years for a focus+field.

Walks the API-only gateway, dedupes pages by URL, and writes a pooled summary.
Use it to expand evidence coverage before the web UI consumes the cache.

Usage:
    python scripts/broad_search.py --focus "西安城墙" --field scenic_history \
        [--years 2023 2024 2025] [--windows d30 m6 y1 y2 y5] \
        [--output-dir probe/broad] [--refresh]

Never prints API keys.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from claimlab.config import load_settings  # noqa: E402
from claimlab.contracts import Requirement, SearchPage, jsonable, make_id  # noqa: E402
from claimlab.runtime import build_sandbox  # noqa: E402
from claimlab.skills.grading import grade_page  # noqa: E402
from claimlab.skills.query import plan_time_series_queries  # noqa: E402

_GRADE_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="Broad time-series search for a focus+field")
    parser.add_argument("--focus", required=True)
    parser.add_argument("--field", required=True)
    parser.add_argument("--years", nargs="*", default=[])
    parser.add_argument("--windows", nargs="*", default=[])
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--refresh", action="store_true", help="bypass the search cache")
    parser.add_argument("--max-plans", type=int, default=12)
    args = parser.parse_args()

    settings = load_settings()
    if not settings.search_key_present:
        print("SEARCH_API_KEY missing; configure .env first")
        return 2

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = None
    if args.output_dir:
        out_dir = Path(args.output_dir)
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print(f"[warn] cannot create output dir {out_dir}: {exc}")
            out_dir = None

    sandbox = build_sandbox(settings)
    gateway = sandbox.new_gateway()
    run_id = f"broad-{args.field}-{stamp}"
    requirement = Requirement(
        requirement_id=make_id("req", args.focus, args.field, stamp),
        text=args.focus,
        field=args.field,
        focus=args.focus,
    )
    plans = plan_time_series_queries(
        requirement,
        focus=args.focus,
        windows=args.windows or None,
        years=args.years or None,
        max_plans=args.max_plans,
    )

    pages_by_url: dict[str, SearchPage] = {}
    executed = []
    try:
        for plan in plans:
            batch = await gateway.search(
                run_id,
                plan.plan_id,
                plan,
                use_cache=not args.refresh,
            )
            for page in batch.pages:
                if page.url:
                    pages_by_url.setdefault(page.url, page)
            executed.append(
                {
                    "query": plan.query,
                    "freshness": plan.freshness,
                    "strategy": plan.strategy,
                    "pages": len(batch.pages),
                    "error": batch.error,
                    "cache_hit": batch.cache_hit,
                }
            )
    finally:
        await sandbox.close()

    pages = list(pages_by_url.values())
    graded = [
        {
            "grade": grade_page(page, field=args.field).grade,
            "url": page.url,
            "domain": page.domain,
            "title": page.title,
            "date": page.date,
        }
        for page in pages
    ]
    grades = {g: sum(1 for item in graded if item["grade"] == g) for g in "ABCDE"}
    summary = {
        "run_id": run_id,
        "field": args.field,
        "focus": args.focus,
        "windows": args.windows or None,
        "years": args.years or None,
        "queries": len(executed),
        "unique_pages": len(pages),
        "grades": grades,
        "executed": executed,
        "sources": sorted(
            graded,
            key=lambda item: (_GRADE_ORDER.get(item["grade"], 9), item.get("date") or ""),
        )[:40],
    }

    if out_dir:
        try:
            raw_path = out_dir / f"{args.field}-{stamp}.json"
            raw_path.write_text(
                json.dumps({"summary": summary, "pages": jsonable(pages)}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            summary_path = out_dir.parent / "broad-summary.json"
            summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"wrote {raw_path}")
        except OSError as exc:
            print(f"[warn] write failed: {exc}")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
