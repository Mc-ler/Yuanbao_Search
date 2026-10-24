"""Text -> falsifiable claims + concerns.

The LLM does the language understanding, but the whitelist and the
falsifiability gate are code. Subjective words become concerns, not verdicts.
A deterministic heuristic keeps the offline demo and tests running without
an LLM key.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..contracts import Claim, ExtractionResult, ResearchTask, make_id

FACT_FIELDS = {
    "business_status",
    "price",
    "hours",
    "penalty",
    "license",
    "address",
    "reservation",
    "ad_disclosure",
    "unknown",
}

SYSTEM_PROMPT = """你是「说法鉴定所」的断言抽取器。任务：把一段中文说法拆成
可被外部事实判定的断言，并区分情绪/主观评价。

规则：
1. 只输出 JSON，不要 Markdown。
2. facts 最多 3 条，按可核验性与重要性排序；每条必须有 field、text、source_sentence。
3. field 只能取：business_status, price, hours, penalty, license, address, reservation, ad_disclosure。
4. 主观评价（难吃、服务差、氛围绝了）放入 emotions，不要放入 facts。
5. 不能改写成原文没有的事实；保留 source_sentence 原句。
6. 不评价个人，不涉及时政。
7. 若无法抽出可证伪的事实，facts 返回空数组。

输出结构：
{"subject": "主体名或空", "facts": [{"text": "...", "field": "...", "value": "...", "source_sentence": "...", "importance": 1}], "emotions": [{"text": "...", "field": "taste|service|wait|hygiene|value", "source_sentence": "..."}], "dropped": [{"text": "...", "reason": "..."}]}
"""


def _sentences(text: str) -> list[str]:
    parts = re.split(r"[。！？!?；;\n]+", text)
    return [part.strip() for part in parts if part.strip()]


def _sentence_for(text: str, needle: str) -> str:
    for sentence in _sentences(text):
        if needle in sentence:
            return sentence
    return ""


def _field_from_text(text: str, aliases: dict[str, str] | None = None) -> str:
    aliases = aliases or {}
    for key, field in aliases.items():
        if key in text:
            return field
    return "unknown"


def _extract_subject(text: str) -> str | None:
    pattern = re.compile(
        r"([\u4e00-\u9fa5A-Za-z0-9·]{2,24}(?:泡馍|肉夹馍|凉皮|面馆|餐厅|饭店|酒店|民宿|景区|博物馆|影城|商场|小吃店|店))"
    )
    match = pattern.search(text)
    return match.group(1) if match else None


def _load_lexicons() -> dict[str, Any]:
    from ..config import CONFIG_DIR

    return json.loads((CONFIG_DIR / "lexicons.json").read_text(encoding="utf-8"))


def heuristic_extract(task: ResearchTask) -> ExtractionResult:
    text = task.text.strip()
    lexicons = _load_lexicons()
    subject = task.subject or _extract_subject(text)
    facts: list[Claim] = []
    emotions: list[Claim] = []
    dropped: list[dict[str, Any]] = []

    def add_fact(field: str, value: Any, claim_text: str, needle: str) -> None:
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
            )
        )

    price_match = re.search(r"(?:人均|每位|价格)\s*[:：]?\s*(\d+(?:\.\d+)?)\s*元?", text)
    if not price_match:
        price_match = re.search(r"(\d+(?:\.\d+)?)\s*元", text)
    if price_match:
        value = float(price_match.group(1))
        add_fact("price", value, f"人均约 {price_match.group(1)} 元", price_match.group(0))

    closed_hit: str | None = None
    for word in lexicons["status_keywords"]["closed"]:
        index = text.find(word)
        if index < 0:
            continue
        context = text[max(0, index - 10) : index + len(word) + 8]
        # "周一闭店" describes weekly hours, not a permanent closure.
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
                    )
                )
                break

    if len(facts) > 3:
        for claim in facts[3:]:
            dropped.append({"text": claim.text, "reason": "超过 3 条可验证断言上限"})
        facts = facts[:3]
    if not facts:
        dropped.append({"text": text[:80], "reason": "未找到可被外部事实判定的断言"})

    return ExtractionResult(facts=facts, emotions=emotions, dropped=dropped, subject=subject, method="heuristic")


def _coerce_claim(item: dict[str, Any], kind: str, task: ResearchTask) -> Claim | None:
    text = str(item.get("text") or "").strip()
    if not text:
        return None
    field = str(item.get("field") or "unknown").strip()
    aliases = _load_lexicons().get("field_aliases", {})
    if field not in FACT_FIELDS:
        field = aliases.get(field, "unknown")
    if kind == "fact" and field == "unknown":
        # Unknown facts are allowed only if the caller marks them falsifiable;
        # prefer dropping to turning a subjective sentence into a "fact".
        if not item.get("falsifiable", True):
            return None
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
    )


async def extract_claims(llm: Any | None, task: ResearchTask) -> ExtractionResult:
    if llm is None:
        return heuristic_extract(task)
    payload = {
        "text": task.text,
        "subject": task.subject,
        "city": task.city,
        "field_whitelist": sorted(FACT_FIELDS - {"unknown"}),
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
        # Trust the model's separation, but do not let an empty result erase
        # clearly verifiable numbers/status that the heuristic can catch.
        if heuristic.facts:
            return heuristic
    subject = str(data.get("subject") or task.subject or "").strip() or None
    return ExtractionResult(
        facts=facts[:3],
        emotions=emotions[:5],
        dropped=dropped,
        subject=subject,
        method="llm",
    )
