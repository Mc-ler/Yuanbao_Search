"""Run the deep research board from the terminal.

    python scripts/run_research.py --text "西安城墙现存主体是什么年代修建的？" --report
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from claimlab.config import load_settings  # noqa: E402
from claimlab.contracts import jsonable  # noqa: E402
from claimlab.planning import build_research_plan  # noqa: E402
from claimlab.research import run_research  # noqa: E402
from claimlab.runtime import build_sandbox  # noqa: E402
from claimlab.skills.research_report import render_research_markdown  # noqa: E402


def read_text(args: argparse.Namespace) -> str:
    if args.text:
        return args.text.strip()
    if args.file:
        return Path(args.file).read_text(encoding="utf-8").strip()
    raise SystemExit("--text or --file is required")


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="Deep research")
    parser.add_argument("--text")
    parser.add_argument("--file")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--report-file")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-screenshots", action="store_true")
    args = parser.parse_args()
    text = read_text(args)
    settings = load_settings()
    if args.no_screenshots:
        settings.screenshot_enabled = False
    sandbox = build_sandbox(settings)
    try:
        plan = await build_research_plan(sandbox.llm, text)
        payload = await run_research(sandbox, text, plan=plan, refresh=args.refresh)
    finally:
        await sandbox.close()
    data = jsonable(payload)
    if args.report or args.report_file:
        markdown = render_research_markdown(data.get("report") or {})
        if args.report:
            print(markdown)
        if args.report_file:
            Path(args.report_file).write_text(markdown, encoding="utf-8")
            print(f"[report] wrote {args.report_file}")
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif not args.report:
        print(json.dumps(data["metrics"], ensure_ascii=False, indent=2))
        for entry in data["source_ledger"]:
            print(f"\n[{entry['field']}] {entry['tier']} unique={entry['unique_pages']}")
            for source in entry["sources"]:
                print(f"  [{source.get('n')}] {source['grade']} {source['domain']} {source['title'][:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
