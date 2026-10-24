"""Run one example through 需求拆分 → 查询构造, without executing search.

The three examples in examples/ have an empty ``question`` on purpose: fill it
manually first. This script is the local mirror of ``POST /api/plan``.

    ./.Search/Scripts/python.exe scripts/run_example.py --example q1_statistics_bulletin
    ./.Search/Scripts/python.exe scripts/run_example.py --example examples/q2_scenic_history.json --json
    ./.Search/Scripts/python.exe scripts/run_example.py --example q3_vehicle_restriction --heuristic
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
from claimlab.llm.client import build_llm  # noqa: E402
from claimlab.skills.query import plan_requirement_queries  # noqa: E402
from claimlab.skills.requirements import decompose_requirements  # noqa: E402


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


async def run(args: argparse.Namespace) -> int:
    path, example = load_example(args.example)
    question = str(example.get("question") or "").strip()
    if not question:
        print(f"question is empty in {path}")
        print("请先手动填入 question；可参考：")
        print(f"  {example.get('question_suggestion') or '(no suggestion)'}")
        print(f"notes: {example.get('notes') or '-'}")
        return 2

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

    llm = None if args.heuristic else build_llm(load_settings())
    try:
        plan = await decompose_requirements(llm, task)
        queries = []
        for requirement in plan.requirements:
            queries.extend(
                plan_requirement_queries(
                    requirement,
                    subject=subject,
                    city=city,
                )
            )
    finally:
        if llm is not None:
            await llm.close()

    payload = {
        "example_id": example.get("example_id") or path.stem,
        "domain": plan.domain or example.get("domain") or "",
        "question": question,
        "method": plan.method,
        "requirements": jsonable(plan.requirements),
        "queries": jsonable(queries),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"example: {payload['example_id']}  domain: {payload['domain']}")
    print(f"method: {plan.method}  requirements: {len(plan.requirements)}  queries: {len(queries)}")
    for requirement in plan.requirements:
        print(f"\n[{requirement.requirement_id}] field={requirement.field} time={requirement.time_window}")
        print(f"  {requirement.text}")
    for query in queries:
        directed = query.site or query.industry or "-"
        print(
            f"  - {query.query}  | {query.precision} | {directed} | {query.freshness or '-'} | {query.strategy}"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="需求拆分 + 查询构造 example runner")
    parser.add_argument("--example", required=True, help="example id or path")
    parser.add_argument("--subject", help="override subject")
    parser.add_argument("--city", help="override city")
    parser.add_argument("--json", action="store_true", help="print JSON")
    parser.add_argument("--heuristic", action="store_true", help="skip LLM, use keyword decomposition")
    args = parser.parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
