"""Conservative input classification for the one-sentence check board.

This is a guardrail, not a semantic parser. It distinguishes questions and
pure opinions from declarative claims so the API can return an actionable
message instead of silently producing a zero-fact report.
"""

from __future__ import annotations

import re

QUESTION_END = ("?", "？")
QUESTION_STARTS = (
    "为什么", "为何", "如何", "怎么", "怎样", "哪", "谁", "何时",
    "什么时候", "多少", "是否", "是不是", "有没有", "能不能", "可不可以",
)
QUESTION_MARKERS = ("吗", "呢", "是否", "是不是", "有没有", "多少", "什么")
OPINION_MARKERS = (
    "难吃", "不好吃", "味道差", "服务差", "态度差", "太贵", "很贵",
    "性价比低", "不干净", "卫生差", "氛围绝了", "惊艳", "好吃",
    "热情", "一般", "排队", "等位",
)
DECLARATIVE_MARKERS = (
    "是", "为", "位于", "建于", "成立于", "发布", "达到", "超过",
    "规定", "要求", "禁止", "允许", "属于", "包括", "拥有", "始于",
    "结束", "举办", "举办过", "被列为", "入选", "同比", "增长",
    "下降", "占比", "约为", "共计", "覆盖", "纳入", "实行",
)


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[。！？!?；;\n]+", text) if part.strip()]


def _has_number_or_date(text: str) -> bool:
    return bool(re.search(r"\d", text)) or bool(re.search(r"(?:19|20)\d{2}\s*年", text))


def classify_input(text: str) -> dict[str, str]:
    raw = (text or "").strip()
    if not raw:
        return {"kind": "empty", "reason": "empty", "suggestion": ""}
    if raw.endswith(QUESTION_END) or raw.startswith(QUESTION_STARTS) or any(marker in raw for marker in QUESTION_MARKERS):
        return {
            "kind": "question",
            "reason": "question_not_claim",
            "guidance": "这是研究问题，请切换到深度研究，或改写成可判定的陈述句。",
            "suggested_claim": _suggest_question_to_claim(raw),
        }
    has_predicate = any(marker in raw for marker in DECLARATIVE_MARKERS) or _has_number_or_date(raw)
    has_opinion = any(marker in raw for marker in OPINION_MARKERS)
    if has_opinion and not has_predicate:
        return {
            "kind": "opinion",
            "reason": "opinion_only",
            "guidance": "这是主观评价，不是可外部核验的事实；请补充价格、时间、地点等客观信息。",
            "suggested_claim": "",
        }
    if has_predicate or _has_number_or_date(raw):
        return {"kind": "declarative", "reason": "", "guidance": "", "suggested_claim": ""}
    return {
        "kind": "ambiguous",
        "reason": "not_declarative",
        "guidance": "没有识别到明确陈述；请用“主体 + 事实 + 数值/时间”的形式重写。",
        "suggested_claim": "",
    }


def _suggest_question_to_claim(text: str) -> str:
    """Only produce a suggestion; never auto-submit it."""
    raw = text.strip().rstrip("?？")
    raw = raw.replace("是否是", "是").replace("是不是", "是").replace("是否", "是").replace("有没有", "有")
    raw = raw.rstrip("吗呢")
    if any(marker in raw for marker in ("什么", "为什么", "如何", "怎样", "多少", "哪", "谁", "何时", "怎么")):
        return ""
    return raw.strip() + "。"


def terms_for(text: str, extra: list[str] | None = None) -> list[str]:
    terms: list[str] = []

    def add(value: str) -> None:
        value = value.strip()
        if value and value not in terms:
            terms.append(value)

    for value in re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", text or ""):
        add(value)
    for value in re.findall(r"\d+(?:\.\d+)?", text or ""):
        if len(value) >= 2:
            add(value)
    for value in re.findall(r"[“\"]([^”\"]{2,24})[”\"]", text or ""):
        add(value)
    for value in extra or []:
        add(value)
    return terms[:8]
