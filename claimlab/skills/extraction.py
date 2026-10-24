"""Text -> falsifiable claims + concerns.

The LLM does language understanding; the input classifier, field mapping and
falsifiability gate are code. The heuristic is intentionally conservative, but
it now covers general declarative statements instead of only local-business
facts. Questions and pure opinions are classified separately so the API can
give an actionable message instead of a silent zero-claim report.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..contracts import Claim, ExtractionResult, ResearchTask, make_id
from .claim_input import classify_input, terms_for

BUSINESS_FIELDS = {
    "business_status",
    "price",
    "hours",
    "penalty",
    "license",
    "address",
    "reservation",
    "ad_disclosure",
}

RESEARCH_FIELDS = {
    "statistics_value",
    "statistics_source",
    "statistics_method",
    "statistics_release",
    "scenic_history",
    "scenic_explanation",
    "heritage_status",
    "municipal_notice",
    "municipal_effective",
    "policy",
    "event",
    "organization",
    "location",
    "science",
}

FACT_FIELDS = BUSINESS_FIELDS | RESEARCH_FIELDS | {"general_fact", "unknown"}

SYSTEM_PROMPT = """你是「万物皆可查」的断言抽取器。任务：把一段中文输入拆成
可被外部事实判定的断言，并区分问题、情绪/主观评价。

规则：
1. 只输出 JSON，不要 Markdown。
2. 先判断输入类型：question / opinion / declarative。问句不是断言；纯主观评价也不是事实；只有 declarative 才抽取 facts。
3. 对 declarative，facts 最多 3 条，按可核验性与重要性排序；每条必须有 field、text、source_sentence。
4. field 优先从以下类型选择：
   business_status, price, hours, penalty, license, address, reservation, ad_disclosure,
   statistics_value, statistics_source, statistics_method, statistics_release,
   scenic_history, scenic_explanation, heritage_status, municipal_notice, municipal_effective,
   policy, event, organization, location, science, general_fact。
   不确定时用 general_fact，不能因为不属于本地商户事实就返回空数组。
5. 历史、统计、政策、公共事件、组织、地点、科学陈述都属于可核验事实；保留原文中的年份、数值、主体和限定条件。
6. 不能改写成原文没有的事实；source_sentence 必须是输入中的原句；text 可以压缩但不能新增实体/数字。
7. 主观评价（难吃、服务差、氛围绝了）放入 emotions，不要放入 facts；没有证据就留空，不要用常识补全。
8. 不评价个人，不涉及时政。
9. 若输入是问句或纯观点，facts 返回空数组，并在 dropped 写明 question_not_claim 或 opinion_only。

输出结构：
{"input_kind":"declarative|question|opinion|ambiguous","subject":"主体名或空","facts":[{"text":"...","field":"general_fact","value":"...","source_sentence":"...","importance":1,"search_terms":["..."]}],"emotions":[{"text":"...","field":"taste|service|wait|hygiene|value","source_sentence":"..."}],"dropped":[{"text":"...","reason":"..."}],"guidance":"可选，给用户的改写建议"}
"""

PROMPT_VERSION = "extract-v3.1"


def _sentences(text: str) -> list[str]:
    parts = re.split(r"[。！？!?；;\n]+", text)
    return [part.strip() for part in parts if part.strip()]


def _sentence_for(text: str, needle: str) -> str:
    for sentence in _sentences(text):
        if needle in sentence:
            return sentence
    return ""


def _extract_subject(text: str) -> str | None:
    pattern = re.compile(
        r"([\u4e00-\u9fa5A-Za-z0-9·（）()]{2,24}(?:泡馍|肉夹馍|凉皮|面馆|餐厅|饭店|酒店|民宿|景区|博物馆|影城|商场|小吃店|店))"
    )
    match = pattern.search(text)
    if not match:
        return None
    subject = match.group(1)
    end = match.end()
    if end < len(text) and text[end] in "）)":
        subject += text[end]
    return subject


def _load_lexicons() -> dict[str, Any]:
    from ..config import CONFIG_DIR

    return json.loads((CONFIG_DIR / "lexicons.json").read_text(encoding="utf-8"))


def _generic_claim(task: ResearchTask, sentence: str, index: int) -> Claim | None:
    clean = sentence.strip()
    if not clean:
        return None
    classification = classify_input(clean)
    if classification.get("kind") in {"question", "opinion"}:
        return None
    # Do not turn a bare noun phrase into a fact. Require a predicate, number,
    # or date. This is deliberately conservative to avoid invented facts.
    if not re.search(
        r"是|为|位于|建于|成立于|发布|达到|超过|规定|禁止|属于|包括|拥有|始于|结束|举办|被列为|入选|\d",
        clean,
    ):
        return None
    terms = terms_for(clean)
    return Claim(
        claim_id=make_id("claim", task.task_id, "general", index, clean[:80]),
        type="fact",
        text=clean[:220],
        field="general_fact",
        value=None,
        source_sentence=clean,
        falsifiable=True,
        importance=index,
        search_terms=terms,
    )


def heuristic_extract(task: ResearchTask) -> ExtractionResult:
    text = task.text.strip()
    classification = classify_input(text)
    kind = classification.get("kind", "declarative")
    subject = _extract_subject(text)
    facts: list[Claim] = []
    emotions: list[Claim] = []
    dropped: list[dict[str, Any]] = []

    if kind == "question":
        dropped.append({"text": text[:120], "reason": "question_not_claim"})
        return ExtractionResult(
            facts=[],
            emotions=[],
            dropped=dropped,
            subject=subject,
            method="heuristic",
            input_kind="question",
            reason="question_not_claim",
            guidance=classification.get("guidance", ""),
        )
    if kind == "opinion":
        lexicons = _load_lexicons()
        for field, words in lexicons["emotion_fields"].items():
            for word in words:
                if word in text:
                    emotions.append(
                        Claim(
                            claim_id=make_id("emotion", task.task_id, field, word),
                            type="emotion",
                            text=word,
                            field=field,
                            source_sentence=_sentence_for(text, word) or text[:120],
                            falsifiable=False,
                            concern=field,
                            search_terms=[],
                        )
                    )
                    break
        dropped.append({"text": text[:120], "reason": "opinion_only"})
        return ExtractionResult(
            facts=[],
            emotions=emotions[:5],
            dropped=dropped,
            subject=subject,
            method="heuristic",
            input_kind="opinion",
            reason="opinion_only",
            guidance=classification.get("guidance", ""),
        )

    lexicons = _load_lexicons()

    def add_fact(field: str, value: Any, claim_text: str, needle: str, terms: list[str] | None = None) -> None:
        facts.append(
            Claim(
                claim_id=make_id("claim", task.task_id, field, claim_text),
                type="fact",
                text=claim_text,
                field=field,
                value=value,
                source_sentence=_sentence_for(text, needle) or text[:120],
                falsifiable=True,
                importance=len(facts),
                search_terms=terms or terms_for(claim_text),
            )
        )

    # Price must use an explicit price context; a bare "41314 元" can be a
    # statistic and must not be misclassified as a restaurant price.
    price_match = re.search(r"(?:人均|每位|价格|消费)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*元?", text)
    if price_match:
        add_fact("price", float(price_match.group(1)), f"人均约 {price_match.group(1)} 元", price_match.group(0))

    closed_hit: str | None = None
    for word in lexicons["status_keywords"]["closed"]:
        index = text.find(word)
        if index < 0:
            continue
        context = text[max(0, index - 10) : index + len(word) + 8]
        if word == "闭店" and any(marker in context for marker in ("周一", "每周", "休息日")):
            continue
        closed_hit = word
        break
    if closed_hit:
        add_fact("business_status", "closed", "该店已闭店或停业", closed_hit)
    elif any(word in text for word in lexicons["status_keywords"]["open"]):
        needle = next(word for word in lexicons["status_keywords"]["open"] if word in text)
        add_fact("business_status", "open", "该店正在营业", needle)

    if "周一" in text and ("闭店" in text or "休息" in text or "不营业" in text):
        add_fact("hours", "monday_closed", "周一闭店", "周一")
    elif "周一至周日" in text:
        add_fact("hours", "all_week", "周一至周日营业", "周一至周日")

    if any(word in text for word in lexicons["penalty_keywords"]["hit"]):
        needle = next(word for word in lexicons["penalty_keywords"]["hit"] if word in text)
        add_fact("penalty", "hit", "存在行政处罚/抽检不合格记录", needle)
    elif any(word in text for word in lexicons["penalty_keywords"]["clear"]):
        needle = next(word for word in lexicons["penalty_keywords"]["clear"] if word in text)
        add_fact("penalty", "clear", "未发现行政处罚记录", needle)

    if "许可证" in text or "资质" in text:
        add_fact("license", "claimed", "该主体具备相应许可/资质", "许可证" if "许可证" in text else "资质")
    if "预约" in text or "限流" in text:
        add_fact("reservation", "needed", "该场所需要预约/限流", "预约" if "预约" in text else "限流")
    if "广告" in text and ("探店" in text or "推广" in text):
        add_fact("ad_disclosure", "missing", "该探店内容可能未标注广告", "广告")

    for field, words in lexicons["emotion_fields"].items():
        for word in words:
            if word in text:
                emotions.append(
                    Claim(
                        claim_id=make_id("emotion", task.task_id, field, word),
                        type="emotion",
                        text=word,
                        field=field,
                        source_sentence=_sentence_for(text, word) or text[:120],
                        falsifiable=False,
                        concern=field,
                        search_terms=[],
                    )
                )
                break

    if not facts and kind in {"declarative", "ambiguous"}:
        for index, sentence in enumerate(_sentences(text), start=1):
            claim = _generic_claim(task, sentence, index)
            if claim is not None:
                facts.append(claim)
            if len(facts) >= 3:
                break

    if len(facts) > 3:
        for claim in facts[3:]:
            dropped.append({"text": claim.text, "reason": "超过 3 条可验证断言上限"})
        facts = facts[:3]
    if not facts:
        dropped.append({"text": text[:120], "reason": "empty_declarative" if kind in {"declarative", "ambiguous"} else "no_falsifiable_claim"})

    return ExtractionResult(
        facts=facts,
        emotions=emotions[:5],
        dropped=dropped,
        subject=subject,
        method="heuristic",
        input_kind=kind,
        reason=classification.get("reason", "") if not facts else "",
        guidance=classification.get("guidance", "") if not facts else "",
    )


def _coerce_claim(item: dict[str, Any], kind: str, task: ResearchTask) -> Claim | None:
    text = str(item.get("text") or "").strip()
    if not text:
        return None
    field = str(item.get("field") or "general_fact").strip()
    aliases = _load_lexicons().get("field_aliases", {})
    if field not in FACT_FIELDS:
        field = aliases.get(field, "general_fact")
    if kind == "fact" and field == "unknown":
        field = "general_fact"
    if kind == "fact" and not item.get("falsifiable", True):
        return None
    search_terms = [
        str(value).strip()
        for value in (item.get("search_terms") or [])
        if str(value).strip()
    ] or terms_for(text)
    return Claim(
        claim_id=make_id("claim", task.task_id, kind, text),
        type="fact" if kind == "fact" else "emotion",
        text=text,
        field=field,
        value=item.get("value"),
        source_sentence=str(item.get("source_sentence") or ""),
        falsifiable=bool(item.get("falsifiable", kind == "fact")),
        importance=int(item.get("importance", 0)),
        concern=item.get("concern") or (field if kind == "emotion" else None),
        search_terms=search_terms,
    )


async def extract_claims(llm: Any | None, task: ResearchTask) -> ExtractionResult:
    classification = classify_input(task.text)
    kind = classification.get("kind", "declarative")
    if kind == "question":
        return heuristic_extract(task)
    if llm is None:
        return heuristic_extract(task)
    payload = {
        "text": task.text,
        "field_whitelist": sorted(FACT_FIELDS - {"unknown"}),
        "prompt_version": PROMPT_VERSION,
        "input_kind": kind,
    }
    try:
        data = await llm.json("extract_claims", payload, SYSTEM_PROMPT)
    except Exception:
        return heuristic_extract(task)
    if not isinstance(data, dict):
        return heuristic_extract(task)
    facts = [
        claim
        for claim in (_coerce_claim(item, "fact", task) for item in data.get("facts") or [] if isinstance(item, dict))
        if claim is not None
    ]
    emotions = [
        claim
        for claim in (_coerce_claim(item, "emotion", task) for item in data.get("emotions") or [] if isinstance(item, dict))
        if claim is not None
    ]
    dropped = [item for item in data.get("dropped") or [] if isinstance(item, dict)]
    if not facts:
        heuristic = heuristic_extract(task)
        if heuristic.facts:
            return heuristic
        if kind in {"declarative", "ambiguous"}:
            if not dropped:
                dropped.append({"text": task.text[:120], "reason": "empty_declarative"})
    subject = str(data.get("subject") or "").strip() or None
    return ExtractionResult(
        facts=facts[:3],
        emotions=emotions[:5],
        dropped=dropped,
        subject=subject,
        method="llm" if facts else "llm_empty",
        input_kind=kind,
        reason=str(data.get("reason") or classification.get("reason") or ""),
        guidance=str(data.get("guidance") or classification.get("guidance") or ""),
    )
