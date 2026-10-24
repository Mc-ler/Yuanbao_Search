"""CLI wrapper for the same live research service used by POST /api/research.

The HTTP UI and this script intentionally share claimlab/research.py, so a result
seen in the terminal can be reproduced in the browser (apart from LLM wording).
This path only exercises the SearchPro API provider.
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
from claimlab.contracts import ResearchTask, jsonable  # noqa: E402
from claimlab.logging import configure_logging  # noqa: E402
from claimlab.research import run_research  # noqa: E402
from claimlab.runtime import build_sandbox  # noqa: E402
from claimlab.skills.research_report import render_research_markdown  # noqa: E402


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


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="Live source validation for examples")
    parser.add_argument("--example", required=True)
    parser.add_argument("--subject")
    parser.add_argument("--city")
    parser.add_argument("--refresh", action="store_true", help="bypass the 72h search cache")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--report", action="store_true", help="print the investigation report as Markdown")
    parser.add_argument("--report-file", help="also write the Markdown report to this path")
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
    sandbox = build_sandbox(settings)
    try:
        payload = await run_research(
            sandbox,
            task,
            example_id=example_id,
            refresh=args.refresh,
        )
    finally:
        await sandbox.close()
    data = jsonable(payload)
    data["log"] = str(log_path)
    if args.report or args.report_file:
        report_md = render_research_markdown(data.get("report") or {})
        if args.report:
            print(report_md)
        if args.report_file:
            Path(args.report_file).write_text(report_md, encoding="utf-8")
            print(f"[report] wrote {args.report_file}")
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(f"{example_id}: {json.dumps(data['metrics'], ensure_ascii=False)}")
        for row in data["results"]:
            print(f"\n[{row['field']}] tier={row['tier']} pages={row['pages']} grades={row['grades']}")
            for query in row["executed"]:
                print(f"  - {query['strategy']}: {query['query']} ({query['pages']} pages)")
            for source in row["top_sources"]:
                print(f"    {source['grade']} [{source['domain']}] {source['title'][:70]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
