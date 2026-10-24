"""Command line entry points for the verifier."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from .config import load_settings
from .contracts import dumps
from .runtime import build_sandbox
from .skills.reporting import render_markdown
from .store.fixtures import fixture_task, load_all_fixtures, load_fixture


def _fixture_path(value: str) -> Path:
    path = Path(value)
    if path.exists():
        return path
    candidate = Path("fixtures") / f"{value}.json"
    if candidate.exists():
        return candidate
    raise SystemExit(f"fixture not found: {value}")


async def _run_fixture(args: argparse.Namespace) -> int:
    settings = load_settings()
    fixture = load_fixture(_fixture_path(args.fixture))
    force_fake = bool(args.fake or not settings.search_api_key)
    if args.offline:
        settings.offline = True
    sandbox = build_sandbox(settings, force_fake=force_fake)
    task = fixture_task(fixture)
    pipeline = sandbox.new_pipeline()
    try:
        report = await pipeline.run(task)
    finally:
        await sandbox.close()
    if args.json:
        print(dumps(report))
    else:
        print(render_markdown(report))
        print()
        print(
            f"[stats] calls={report.stats.calls} cache={report.stats.cache_hits} "
            f"results={report.stats.results} unique={report.stats.unique_results} "
            f"clusters={report.stats.clusters} a={report.stats.a_level} b={report.stats.b_level} "
            f"stop={report.stats.stop_reason}"
        )
    return 0


async def _doctor() -> int:
    settings = load_settings()
    sandbox = build_sandbox(settings)
    try:
        health = await sandbox.health()
    finally:
        await sandbox.close()
    print(json.dumps(health, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="claimlab", description="YuanBao Search claim verifier")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run a fixture through the pipeline")
    run.add_argument("--fixture", required=True, help="fixture id or path")
    run.add_argument("--offline", action="store_true", help="use cache only; no live calls")
    run.add_argument("--fake", action="store_true", help="force the offline fixture provider")
    run.add_argument("--json", action="store_true", help="print contract C as JSON")
    run.set_defaults(func=lambda args: asyncio.run(_run_fixture(args)))

    serve = sub.add_parser("serve", help="start the web UI and API")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)
    serve.set_defaults(func=_serve)

    doctor = sub.add_parser("doctor", help="print configuration and provider health")
    doctor.set_defaults(func=lambda args: asyncio.run(_doctor()))

    fixtures = sub.add_parser("fixtures", help="list local fixtures")
    fixtures.set_defaults(func=_list_fixtures)

    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    settings = load_settings()
    uvicorn.run(
        "claimlab.api:app",
        host=args.host or settings.app_host,
        port=args.port or settings.app_port,
        reload=False,
    )
    return 0


def _list_fixtures(args: argparse.Namespace) -> int:
    for fixture in load_all_fixtures().values():
        print(f"{fixture.get('fixture_id')}: {fixture.get('title')}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
