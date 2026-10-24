"""Summarize probe and run artifacts for source-quality debugging.

Reads probe/summary.json and archive/run-*.jsonl. Prints page counts, queries,
domains and providers; never prints keys or full page bodies.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def official(domain: str) -> bool:
    return domain.endswith(".gov.cn") or domain in {"gov.cn", "stats.gov.cn", "mct.gov.cn", "mot.gov.cn"}


def main() -> None:
    summary_path = ROOT / "probe" / "summary.json"
    if summary_path.exists():
        probes = json.loads(summary_path.read_text(encoding="utf-8"))
        print(f"M1 probes: {len(probes)}")
        for item in probes:
            req = item.get("request") or {}
            print(
                f"  {item.get('provider'):4} {item.get('probe'):12} "
                f"pages={item.get('pages'):>2} first={item.get('first_domain') or '-':22} "
                f"query={req.get('Query')}"
            )
        print()

    runs = sorted((ROOT / "archive").glob("run-*.jsonl"))
    print(f"archive runs: {len(runs)}")
    real_runs = 0
    real_searches = 0
    real_pages = 0
    domain_counts: Counter[str] = Counter()
    official_pages = 0
    for path in runs:
        events = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        providers = {
            str(event.get("payload", {}).get("provider"))
            for event in events
            if event.get("type") in {"search", "search.result"}
        }
        providers.discard("None")
        if not providers or providers == {"fake"}:
            continue
        real_runs += 1
        print(f"\n{path.name} providers={sorted(providers)}")
        for event in events:
            if event.get("type") != "search":
                continue
            payload = event.get("payload") or {}
            response = payload.get("response") or {}
            pages = response.get("pages") or []
            query = (payload.get("request") or {}).get("Query") or ""
            domains = [str(page.get("domain") or "") for page in pages]
            domain_counts.update(domains)
            real_searches += 1
            real_pages += len(pages)
            official_pages += sum(1 for domain in domains if official(domain))
            print(
                f"  {payload.get('provider'):4} pages={len(pages):>2} "
                f"official={sum(1 for d in domains if official(d)):>2} query={query[:80]}"
            )
            if domains:
                print(f"       domains={', '.join(domains[:6])}")
    print("\nreal runs:", real_runs)
    print("real searches:", real_searches)
    print("real pages:", real_pages)
    print("official pages:", official_pages)
    print("top domains:", domain_counts.most_common(15))


if __name__ == "__main__":
    main()
