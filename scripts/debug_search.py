"""Live query diagnosis for the statistics example.

Runs a small matrix of generic vs target-specific queries and records page
counts, official domains and zero-result cases. Use this before changing query
templates; it does not use the pipeline budget.

    python scripts/debug_search.py --matrix q1 --gov
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
from claimlab.contracts import SearchRequest  # noqa: E402
from claimlab.logging import configure_logging, event  # noqa: E402
from claimlab.search.api import ApiSearchProvider  # noqa: E402

debug_log = logging.getLogger("claimlab.debug")

Q1_QUERIES = [
    "国家统计局 统计公报 数据来源",
    "国家统计局 统计口径",
    "国家统计局 统计口径 来源",
    "国家统计局 2024 居民人均可支配收入 41314",
    "国家统计局 住户调查 居民人均可支配收入",
    "2024年 居民人均可支配收入 统计公报",
    "国家统计局 居民收入和消费支出情况 2024",
    "国家统计局 住户调查制度 统计口径",
]


def official(domain: str) -> bool:
    return domain.endswith(".gov.cn") or domain in {"gov.cn", "stats.gov.cn"}


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="Debug SearchPro query terms")
    parser.add_argument("--matrix", default="q1", help="q1 or omit")
    parser.add_argument("--query", action="append", default=[], help="custom query; repeatable")
    parser.add_argument("--gov", action="store_true", help="also test Industry=gov")
    parser.add_argument("--cnt", type=int, default=10)
    args = parser.parse_args()

    settings = load_settings()
    if not settings.search_api_key:
        print("SEARCH_API_KEY missing")
        return 2
    queries = args.query or (Q1_QUERIES if args.matrix == "q1" else [])
    if not queries:
        print("no queries")
        return 2

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    logs_dir = ROOT / "logs"
    raw_dir = ROOT / "probe" / "debug"
    logs_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    log_path = configure_logging(
        logs_dir,
        f"debug-search-{stamp}.log",
        level=settings.log_level,
        max_bytes=settings.log_max_bytes,
        backup_count=settings.log_backup_count,
    )
    raw_path = raw_dir / f"debug-search-{stamp}.json"
    records: list[dict] = []
    provider = ApiSearchProvider(settings)
    try:
        for query in queries:
            industries = [None, "gov"] if args.gov else [None]
            for industry in industries:
                request = SearchRequest(query=query, cnt=args.cnt, industry=industry, freshness="y2")
                batch = await provider.search(request)
                pages = batch.pages
                domains = [page.domain for page in pages]
                official_count = sum(1 for domain in domains if official(domain))
                record = {
                    "query": query,
                    "industry": industry,
                    "ok": batch.ok,
                    "pages": len(pages),
                    "official": official_count,
                    "latency_ms": batch.latency_ms,
                    "error": batch.error,
                    "domains": domains,
                    "titles": [page.title for page in pages[:5]],
                }
                records.append(record)
                line = (
                    f"{query!r} industry={industry or '-'} pages={len(pages)} "
                    f"official={official_count} latency={batch.latency_ms:.0f}ms "
                    f"domains={','.join(domains[:6]) or '-'}"
                )
                print(line)
                event(
                    debug_log,
                    "debug.query",
                    query=query,
                    industry=industry,
                    pages=len(pages),
                    official=official_count,
                    latency_ms=round(batch.latency_ms, 1),
                    domains=domains[:8],
                    error=batch.error,
                )
    finally:
        await provider.close()
    raw_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"log: {log_path}")
    print(f"raw: {raw_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
