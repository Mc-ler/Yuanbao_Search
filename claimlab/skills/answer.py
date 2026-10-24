"""Conclusion + numbered-citation answer generation (no-fabrication).

The research answer stage deliberately receives citation metadata and optional
page screenshots, not the full retrieved passage. Screenshots are attached as
vision inputs; the model must say "未获证据" when it cannot read one.
"""

from __future__ import annotations

from typing import Any

from .citations import citation_numbers, validate_citations

NO_RESULT_TEXT = "不知道：当前没有检索到可核验的结果，无法确定。"

SYSTEM_PROMPT = """你是研究综述生成器。给定一个研究问题、一组带编号的来源元数据和可选的网页截图，产出可核验的研究综述。只输出 JSON。
规则：
1. 只依据给定来源元数据、内容节选和截图作答；禁止编造来源里没有的出处、日期、文号、机构、人物、数字。
2. 每个事实句后带 [n] 引用编号；没有来源支撑的句子必须写（未获证据），并明确说“不知道/没有结果/无法确定”，不得猜测。
3. 截图是来源 [n] 的页面截图；截图看不清、被登录墙挡住或与问题无关时，写（未获证据），不要猜。
4. 这是研究综述，不是 R1–R5 判定；不要输出“成立/不成立/已证实”等判定词，除非来源本身明确写了。
5. 先给结论，再给依据；不确定就直说“不确定/需核实”。
输出：{"text":"...","citations_used":[1,2],"uncertainty":"..."}
"""


def _sources_for(row: dict[str, Any]) -> list[dict[str, Any]]:
    return list(row.get("top_sources") or row.get("sources") or [])


def build_citations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedupe sources by cluster (fallback URL) and assign [1..N] numbers."""
    seen: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in rows or []:
        for src in _sources_for(row):
            url = (src.get("url") or "").strip()
            if not url:
                continue
            key = str(src.get("cluster_id") or url)
            if key in seen:
                continue
            seen[key] = src
            order.append(key)
    citations: list[dict[str, Any]] = []
    for index, key in enumerate(order, start=1):
        src = seen[key]
        citations.append(
            {
                "n": index,
                "url": (src.get("url") or "").strip(),
                "title": src.get("title") or "",
                "domain": src.get("domain") or "",
                "grade": src.get("grade") or "",
                "date": src.get("date") or "",
                "passage": src.get("passage") or "",
                "content_excerpt": src.get("content_excerpt") or "",
                "cluster_id": src.get("cluster_id") or "",
                "cluster_size": src.get("cluster_size") or 1,
                "cluster_domains": src.get("cluster_domains") or [],
            }
        )
    return citations


def _rule_answer(rows: list[dict[str, Any]], citations: list[dict[str, Any]]) -> str:
    if not rows:
        return NO_RESULT_TEXT
    lines: list[str] = []
    for row in rows:
        field = row.get("field") or "结论"
        tier = row.get("tier") or "insufficient"
        if tier == "A/B":
            verdict = "有 A/B 级来源可读，尚无模型综述"
        elif tier == "B/C":
            verdict = "仅有 B/C 降级来源，尚无模型综述"
        else:
            verdict = "没有结果，无法确定"
        srcs = _sources_for(row)
        refs = []
        for c in citations:
            for src in srcs:
                if (src.get("url") or "") == c["url"]:
                    refs.append(str(c["n"]))
                    break
        suffix = ("（引用 " + "、".join("[" + r + "]" for r in refs[:5]) + "）") if refs else ""
        lines.append("- " + field + "：" + verdict + suffix)
    return "\n".join(lines)


def _evidence_text(citations: list[dict[str, Any]]) -> str:
    lines = []
    for c in citations:
        lines.append(
            "[" + str(c["n"]) + "] (" + (c["grade"] or "?") + ") " + (c["title"] or "")
            + " — " + (c["domain"] or "") + " " + (c["date"] or "")
            + "\nURL: " + c["url"]
            + ("\n内容节选: " + str(c.get("content_excerpt") or "") if c.get("content_excerpt") else "")
        )
    return "\n".join(lines)


def _merge_screenshot_meta(
    citations: list[dict[str, Any]],
    screenshots: dict[int, dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    result = []
    for citation in citations:
        meta = (screenshots or {}).get(int(citation["n"])) or {}
        item = dict(citation)
        item["screenshot_url"] = meta.get("url")
        item["screenshot_captured"] = bool(meta.get("captured"))
        item["screenshot_error"] = meta.get("error")
        result.append(item)
    return result


def _response(
    text: str,
    engine: str,
    citations: list[dict[str, Any]],
    citations_used: list[int],
    citation_issues: list[dict[str, Any]],
    uncertainty: str,
) -> dict[str, Any]:
    screenshot_list = [
        {
            "n": c["n"],
            "url": c.get("screenshot_url"),
            "captured": c.get("screenshot_captured", False),
            "error": c.get("screenshot_error"),
        }
        for c in citations
        if c.get("screenshot_url") or c.get("screenshot_error")
    ]
    return {
        "text": text,
        "answer": text,  # backward-compatible alias
        "engine": engine,
        "citations": citations,
        "citations_used": citations_used,
        "citation_issues": citation_issues,
        "screenshots": screenshot_list,
        "uncertainty": uncertainty,
    }


async def build_answer(
    llm: Any,
    question: str,
    rows: list[dict[str, Any]],
    *,
    images: list[dict[str, Any]] | None = None,
    screenshots: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    citations = _merge_screenshot_meta(build_citations(rows), screenshots)
    if not citations:
        return _response(
            NO_RESULT_TEXT,
            "rule",
            [],
            [],
            [],
            "无证据",
        )

    data = None
    if llm is not None:
        payload = {"question": question, "evidence": _evidence_text(citations)}
        try:
            data = await llm.json("answer", payload, SYSTEM_PROMPT, images=images or None)
        except Exception:
            data = None

    if isinstance(data, dict) and (str(data.get("text") or data.get("answer") or "")).strip():
        text, issues = validate_citations(str(data.get("text") or data.get("answer")).strip(), citations)
        valid_refs = citation_numbers(text, citations)
        if citations and not valid_refs:
            issues.append({"n": 0, "reason": "no_valid_citation"})
            fallback = _rule_answer(rows, citations)
            return _response(fallback, "rule", citations, [], issues, "模型未给出有效引用，已退回规则摘要")
        used = [
            int(x)
            for x in (data.get("citations_used") or [])
            if isinstance(x, (int, float)) and 1 <= int(x) <= len(citations)
        ]
        return _response(
            text,
            "llm",
            citations,
            used or valid_refs,
            issues,
            str(data.get("uncertainty") or ""),
        )

    return _response(
        _rule_answer(rows, citations),
        "rule",
        citations,
        [c["n"] for c in citations[:6]],
        [],
        "离线规则汇总，未经大模型逐句核验",
    )
