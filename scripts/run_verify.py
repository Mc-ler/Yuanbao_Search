"""Run the claim verification board from the terminal.

    python scripts/run_verify.py --text "该店人均68元，周一闭店。" --report
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
from claimlab.contracts import ResearchTask, jsonable  # noqa: E402
from claimlab.runtime import build_sandbox  # noqa: E402
from claimlab.skills.reporting import render_markdown  # noqa: E402


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="Claim verification (R1-R5)")
    parser.add_argument("--text", required=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()
    settings = load_settings()
    sandbox = build_sandbox(settings)
    try:
        pipeline = sandbox.new_pipeline()
        report = await pipeline.run(ResearchTask(text=args.text.strip(), mode="verify_claim"))
    finally:
        await sandbox.close()
    if args.json:
        print(json.dumps(jsonable(report), ensure_ascii=False, indent=2))
    elif args.report:
        print(render_markdown(report))
    else:
        print(render_markdown(report))
        print()
        print(
            f"[stats] calls={report.stats.calls} cache={report.stats.cache_hits} "
            f"results={report.stats.results} clusters={report.stats.clusters} "
            f"stop={report.stats.stop_reason}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
