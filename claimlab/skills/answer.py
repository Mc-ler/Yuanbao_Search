"""Conclusion + numbered-citation answer generation (no-fabrication)."""

from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """你是查证结论生成器。给定一个问题与一组带编号的证据来源，产出可核验结论。只输出 JSON。
规则：
1. 只依据给定证据作答，禁止编造证据里没有的出处、日期、文号、机构、人物、数字。
2. 每个事实句后带 [n] 引用编号；没有来源支撑的句子必须写（未获证据）。
3. 证据与问题无关或不足时，明确输出"无法确认"，并逐条说明证据为何不相关。
4. 先给结论，再给依据；不确定就直说"不确定/需核实"。
输出：{"answer":"...","verdict":"...","citations_used":[1,2],"uncertainty":"..."}
"""


def build_citations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedupe sources by URL and assign [1..N] numbers."""
    seen: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in rows or []:
        for src in row.get("top_sources") or []:
            url = (src.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen[url] = src
            order.append(url)
    return [
        {
            "n": i + 1,
            "url": url,
            "title": seen[url].get("title") or "",
            "domain": seen[url].get("domain") or "",
            "grade": seen[url].get("grade") or "",
            "date": seen[url].get("date") or "",
        }
        for i, url in enumerate(order)
    ]


def _rule_answer(rows: list[dict[str, Any]], citations: list[dict[str, Any]]) -> str:
    if not rows:
        return "没有可分析的需求，无法给出结论。"
    lines: list[str] = []
    for row in rows:
        field = row.get("field") or "结论"
        tier = row.get("tier") or "insufficient"
        if tier == "A/B":
            verdict = "有可靠来源佐证"
        elif tier == "B/C":
            verdict = "有较可靠来源（B/C 级），倾向成立"
        else:
            verdict = "无法确认"
        srcs = row.get("top_sources") or []
        refs = []
        for c in citations:
            for src in srcs:
                if (src.get("url") or "") == c["url"]:
                    refs.append(str(c["n"]))
                    break
        suffix = ("（引用 " + "、".join("[" + r + "]" for r in refs[:5]) + "）") if refs else ""
        lines.append("- " + field + "：" + verdict + suffix)
    return "\n".join(lines)


async def build_answer(llm: Any, question: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    citations = build_citations(rows)
    if not citations:
        return {
            "answer": "未检索到任何可引用来源，无法给出结论。",
            "verdict": "无法确认",
            "citations": [],
            "engine": "rule",
            "uncertainty": "无证据",
        }

    evidence_lines = []
    for c in citations:
        evidence_lines.append(
            "[" + str(c["n"]) + "] (" + (c["grade"] or "?") + ") " + (c["title"] or "")
            + " — " + (c["domain"] or "") + " " + (c["date"] or "") + "\n" + c["url"]
        )
    evidence = "\n".join(evidence_lines)

    data = None
    if llm is not None:
        try:
            data = await llm.json("answer", {"question": question, "evidence": evidence}, SYSTEM_PROMPT)
        except Exception:
            data = None

    if isinstance(data, dict) and (data.get("answer") or "").strip():
        used = [
            int(x)
            for x in (data.get("citations_used") or [])
            if isinstance(x, (int, float)) and 1 <= int(x) <= len(citations)
        ]
        return {
            "answer": str(data.get("answer") or "").strip(),
            "verdict": str(data.get("verdict") or ""),
            "citations": citations,
            "citations_used": used,
            "engine": "llm",
            "uncertainty": str(data.get("uncertainty") or ""),
        }

    return {
        "answer": _rule_answer(rows, citations),
        "verdict": "待核实",
        "citations": citations,
        "citations_used": [c["n"] for c in citations[:6]],
        "engine": "rule",
        "uncertainty": "离线规则汇总，未经大模型逐句核验",
    }
