"""Pre-generate demo research (plans + results) for the examples in examples/.

Runs each filled example through the real research flow once, then saves the
complete payload (requirements / queries / results / metrics / answer / report)
into demos/<example_id>.json for offline exact-match reuse.

Usage:
    python scripts/prepare_demos.py [--refresh]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from claimlab.config import load_settings  # noqa: E402
from claimlab.contracts import ResearchTask, jsonable  # noqa: E402
from claimlab.demos import save_demo  # noqa: E402
from claimlab.research import run_research  # noqa: E402
from claimlab.runtime import build_sandbox  # noqa: E402


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="Pre-generate demo research payloads")
    parser.add_argument("--refresh", action="store_true", help="bypass the search cache")
    args = parser.parse_args()

    settings = load_settings()
    if not settings.search_key_present:
        print("SEARCH_API_KEY missing; configure .env first")
        return 2

    examples_dir = ROOT / "examples"
    sandbox = build_sandbox(settings)
    try:
        for path in sorted(examples_dir.glob("*.json")):
            try:
                example = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(example, dict):
                continue
            question = str(example.get("question") or "").strip()
            if not question:
                continue
            example_id = str(example.get("example_id") or path.stem)
            task = ResearchTask(
                text=question,
                mode="research_topic",
                subject=(example.get("subject") or "").strip() or None,
                city=(example.get("city") or "").strip() or None,
                constraints={
                    "domain": example.get("domain") or "",
                    "expected_sources": example.get("expected_sources") or [],
                    "query_fields": example.get("query_fields") or [],
                },
            )
            payload = await run_research(sandbox, task, example_id=example_id, refresh=args.refresh)
            payload = jsonable(payload)
            payload["example_id"] = example_id
            payload["question"] = question
            payload["demo"] = True
            out_path = save_demo(example_id, payload)
            print(f"prepared {example_id} -> {out_path} (fields={payload['metrics']['fields']}, pages={payload['metrics']['pages']})")
        return 0
    finally:
        await sandbox.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
