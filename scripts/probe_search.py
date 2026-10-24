"""Probe the live Yuanbao Search API and MCP transports.

Run after putting SEARCH_API_KEY in .env:
    ./.Search/Scripts/python.exe scripts/probe_search.py --provider both

Writes normalized pages and raw responses under probe/raw/. This script is
intentionally outside the app pipeline so latency and field differences are
measured without cache or budget interference.
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
from claimlab.contracts import SearchRequest, jsonable  # noqa: E402
from claimlab.logging import configure_logging, event  # noqa: E402
from claimlab.search.api import ApiSearchProvider  # noqa: E402
from claimlab.search.mcp import MCP_SDK_AVAILABLE, McpSearchProvider  # noqa: E402

probe_log = logging.getLogger("claimlab.probe")

PROBES = [
    {"name": "P1 公众号索引", "query": "西安 探店", "site": "mp.weixin.qq.com"},
    {"name": "P2 裸查询", "query": "西安 回民街 必吃"},
    {"name": "P3 酒店 VR", "query": "西安 钟楼 附近 酒店", "mode": 1},
    {"name": "P4 必吃榜 VR", "query": "西安 必吃榜 餐厅", "mode": 1},
    {"name": "P5 票务混合", "query": "长恨歌 演出 门票", "mode": 2},
    {"name": "P6 携程游记", "query": "西安 三日游", "site": "you.ctrip.com"},
    {"name": "P7 小红书索引", "query": "西安 探店", "site": "xiaohongshu.com"},
    {"name": "P8 政府定向", "query": "西安 城墙 门票", "industry": "gov"},
]


async def probe_one(provider_name: str, provider, spec: dict, out_dir: Path) -> dict:
    request = SearchRequest(
        query=spec["query"],
        mode=int(spec.get("mode", 0)),
        site=spec.get("site"),
        cnt=int(spec.get("cnt", 10)),
        industry=spec.get("industry"),
        freshness=spec.get("freshness"),
    )
    batch = await provider.search(request)
    first = batch.pages[0] if batch.pages else None
    record = {
        "provider": provider_name,
        "probe": spec["name"],
        "request": request.to_api_body(),
        "ok": batch.ok,
        "error": batch.error,
        "version": batch.version,
        "request_id": batch.request_id,
        "latency_ms": round(batch.latency_ms, 1),
        "pages": len(batch.pages),
        "first_title": first.title if first else None,
        "first_domain": first.domain if first else None,
        "first_has_content": bool(first and first.content) if first else False,
        "first_has_pics": bool(first and first.pics) if first else False,
        "warnings": batch.warnings,
        "normalized_pages": [jsonable(page) for page in batch.pages],
        "raw": batch.raw,
    }
    filename = f"{provider_name}-{spec['name'].split()[0]}.json"
    (out_dir / filename).write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    status = "ok" if batch.ok else f"ERROR {batch.error}"
    domains = [page.domain for page in batch.pages if page.domain]
    official = sum(1 for domain in domains if domain.endswith(".gov.cn") or domain in {"gov.cn", "stats.gov.cn"})
    event(
        probe_log,
        "probe.search",
        level=logging.INFO if batch.ok and batch.pages else logging.WARNING,
        provider=provider_name,
        probe=spec["name"],
        query=request.query,
        pages=len(batch.pages),
        official=official,
        domains=domains[:8],
        latency_ms=round(batch.latency_ms, 1),
        error=batch.error,
    )
    print(
        f"{provider_name:4} {spec['name']:16} pages={len(batch.pages):2} "
        f"version={batch.version or '-':8} {round(batch.latency_ms):5}ms  {status}"
    )
    if first:
        print(f"      first: [{first.domain}] {first.title[:80]}")
    return record


async def main_async(args: argparse.Namespace) -> int:
    settings = load_settings()
    if not settings.search_key_present:
        print("SEARCH_API_KEY is not configured in .env; refusing to run a fake probe.")
        return 2
    out_dir = settings.root / "probe" / "raw"
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = configure_logging(
        settings.logs_dir,
        f"probe-search-{datetime.now():%Y%m%d-%H%M%S}.log",
        level=settings.log_level,
        max_bytes=settings.log_max_bytes,
        backup_count=settings.log_backup_count,
    )
    event(probe_log, "probe.start", provider=args.provider, log=log_path)
    providers = []
    if args.provider in {"api", "both"}:
        providers.append(("api", ApiSearchProvider(settings)))
    if args.provider in {"mcp", "both"}:
        providers.append(("mcp", McpSearchProvider(settings)))
        if not MCP_SDK_AVAILABLE:
            print("MCP SDK not installed; using the built-in JSON-RPC fallback.")
    records = []
    try:
        for name, provider in providers:
            for spec in PROBES[: args.limit or len(PROBES)]:
                try:
                    records.append(await probe_one(name, provider, spec, out_dir))
                except Exception as exc:
                    print(f"{name:4} {spec['name']:16} EXCEPTION {type(exc).__name__}: {exc}")
    finally:
        for _, provider in providers:
            try:
                await provider.close()
            except Exception:
                pass
    summary = settings.root / "probe" / "summary.json"
    summary.write_text(json.dumps(records, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nSaved {len(records)} probes to {out_dir}")
    return 0 if any(item.get("ok") for item in records) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe Yuanbao Search API and MCP")
    parser.add_argument("--provider", choices=["api", "mcp", "both"], default="both")
    parser.add_argument("--limit", type=int, default=0, help="limit probes per provider")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
