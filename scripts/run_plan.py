"""Preview the shared research plan (no search)."""

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
from claimlab.runtime import build_sandbox  # noqa: E402


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="Research plan preview")
    parser.add_argument("--text", required=True)
    args = parser.parse_args()
    settings = load_settings()
    sandbox = build_sandbox(settings)
    try:
        plan = await build_research_plan(sandbox.llm, args.text.strip())
    finally:
        await sandbox.close()
    print(json.dumps(jsonable(plan.as_dict()), ensure_ascii=False, indent=2))
    print(f"\nplan_id={plan.plan_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
