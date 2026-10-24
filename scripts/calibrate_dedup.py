"""Calibrate the dedup threshold on real probe passages.

Run after scripts/probe_search.py:
    ./.Search/Scripts/python.exe scripts/calibrate_dedup.py

Reads probe/raw/*.json, prints the pairwise Jaccard distribution, and writes
probe/calibration.md with candidate thresholds and examples.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from claimlab.skills.dedup import jaccard, shingles  # noqa: E402


def main() -> int:
    raw_dir = ROOT / "probe" / "raw"
    files = sorted(raw_dir.glob("*.json"))
    if not files:
        print("No probe files. Run scripts/probe_search.py first.")
        return 2
    pairs = []
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        pages = data.get("normalized_pages") or []
        for i in range(len(pages)):
            for j in range(i + 1, len(pages)):
                a = pages[i].get("passage") or pages[i].get("content") or pages[i].get("title") or ""
                b = pages[j].get("passage") or pages[j].get("content") or pages[j].get("title") or ""
                score = jaccard(shingles(a), shingles(b))
                pairs.append(
                    {
                        "probe": data.get("probe"),
                        "provider": data.get("provider"),
                        "a": pages[i].get("url"),
                        "b": pages[j].get("url"),
                        "score": round(score, 4),
                    }
                )
    pairs.sort(key=lambda item: item["score"], reverse=True)
    top = pairs[:20]
    distribution = {"gte_0.8": 0, "gte_0.7": 0, "gte_0.6": 0, "gte_0.5": 0, "gte_0.3": 0, "lt_0.3": 0}
    for item in pairs:
        score = item["score"]
        if score >= 0.8:
            distribution["gte_0.8"] += 1
        elif score >= 0.7:
            distribution["gte_0.7"] += 1
        elif score >= 0.6:
            distribution["gte_0.6"] += 1
        elif score >= 0.5:
            distribution["gte_0.5"] += 1
        elif score >= 0.3:
            distribution["gte_0.3"] += 1
        else:
            distribution["lt_0.3"] += 1
    print("pair distribution:", json.dumps(distribution, ensure_ascii=False))
    print("top pairs:")
    for item in top[:10]:
        print(f"  {item['score']:.3f}  {item['a']}  <->  {item['b']}")
    lines = [
        "# 去重阈值标定卡",
        "",
        f"样本文件：{len(files)}；两两比较：{len(pairs)}",
        "",
        "## 分布",
        "",
        "```json",
        json.dumps(distribution, ensure_ascii=False, indent=2),
        "```",
        "",
        "## 建议",
        "",
        "- 默认 θ = 0.65；若同源转载占比高，候选 0.70–0.75。",
        "- 这里的相似度只基于摘要，阈值应低于正文场景。",
        "",
        "## 高相似样本",
        "",
    ]
    for item in top:
        lines.append(f"- {item['score']:.3f} · {item['a']} · {item['b']}")
    (ROOT / "probe").mkdir(exist_ok=True)
    (ROOT / "probe" / "calibration.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote probe/calibration.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
