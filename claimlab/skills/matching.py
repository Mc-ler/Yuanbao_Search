"""Evidence -> support/refute/unrelated with a verified quote.

The model may read the passage, but it cannot invent a quote: a match whose
quote is not a substring of the retrieved text is downgraded to unrelated.
The heuristic is the offline fallback and a useful regression baseline.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from ..config import CONFIG_DIR
from ..contracts import Claim, SearchPage
from ..logging import event

logger = logging.getLogger("claimlab.matching")

# A reasoning model spends output tokens on each evidence item. Eight items per
# call keeps the JSON well inside the budget while avoiding 20+ round trips.
BATCH_SIZE = 8

SYSTEM_PROMPT = """你是证据匹配器。给定一条断言和一批检索结果，判断每条结果与断言的关系。
只输出 JSON。每条结果必须返回一个 match：
- relation: support / refute / unrelated
- quote: 必须从 passage 或 content 中原样截取的一句话；找不到原句就返回 unrelated 且 quote 为空
- observed_value: 结果中出现的具体值（如 68、128、周一闭店），没有就为空
规则：
1. 不要因为标题相关就判 support。
2. 摘要没有提到断言核心字段时，判 unrelated。
3. 不要评价个人，不做动机推断；证据不足或自相矛盾时返回 unrelated，不要猜测。
4. 不要改写原文。
5. 只依据原文直接判断；需要常识补全、猜测年份/因果/身份时，必须返回 unrelated。
6. 对通用事实，只有原文明确支持或反驳该断言时才返回 support/refute；相关但不足以判断时返回 unrelated。
输出：{"matches":[{"evidence_id":"e1","relation":"support|refute|unrelated","quote":"...","observed_value":"...","reason":"..."}]}
"""


@dataclass
class MatchResult:
    page_index: int
    relation: str
    quote: str = ""
    observed_value: str | None = None
    reason: str = ""
    quote_rejected: bool = False


def _lexicons() -> dict[str, Any]:
    return json.loads((CONFIG_DIR / "lexicons.json").read_text(encoding="utf-8"))


def _numbers(text: str) -> list[float]:
    values: list[float] = []
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*元", text):
        try:
            values.append(float(match.group(1)))
        except ValueError:
            pass
    for match in re.finditer(r"人均\s*[:：]?\s*(\d+(?:\.\d+)?)", text):
        try:
            value = float(match.group(1))
            if value not in values:
                values.append(value)
        except ValueError:
            pass
    return values


def _format_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def _sentence_with(text: str, needle: str) -> str:
    if not needle:
        return ""
    for sentence in re.split(r"[。！？!?；;\n]+", text):
        if needle in sentence:
            return sentence.strip()
    return ""


def _normalize_quote(value: str) -> str:
    return re.sub(r"[\s\u3000]+", "", value or "")


def heuristic_match(claim: Claim, page: SearchPage) -> MatchResult:
    text = page.text()
    field = claim.field
    value = claim.value

    if field == "price":
        numbers = _numbers(text)
        if numbers and value is not None:
            try:
                target = float(value)
            except (TypeError, ValueError):
                target = None
            if target is not None:
                if any(abs(number - target) <= 0.5 for number in numbers):
                    number = min(numbers, key=lambda item: abs(item - target))
                    return MatchResult(-1, "support", _sentence_with(text, _format_number(number)), _format_number(number))
                return MatchResult(-1, "refute", _sentence_with(text, _format_number(numbers[0])), _format_number(numbers[0]))
        return MatchResult(-1, "unrelated")

    if field == "business_status":
        status = str(value or "")
        strong_closed = any(word in text for word in ("已闭店", "停业", "注销", "歇业", "关门", "暂停营业"))
        weekly_closed = ("周一" in text or "每周" in text) and ("闭店" in text or "休息" in text)
        opened = any(word in text for word in ("正常营业", "营业中", "正在营业", "开门"))
        if status in {"open", "营业中", "营业"}:
            if strong_closed:
                return MatchResult(-1, "refute", _sentence_with(text, "停业") or _sentence_with(text, "闭店"), "closed")
            if opened:
                return MatchResult(-1, "support", _sentence_with(text, "营业"), "open")
            return MatchResult(-1, "unrelated")
        if status in {"closed", "闭店", "停业"}:
            if strong_closed:
                return MatchResult(-1, "support", _sentence_with(text, "停业") or _sentence_with(text, "闭店"), "closed")
            if weekly_closed:
                return MatchResult(-1, "unrelated")
            if opened:
                return MatchResult(-1, "refute", _sentence_with(text, "营业"), "open")
        return MatchResult(-1, "unrelated")

    if field == "penalty":
        lexicons = _lexicons()
        hit = [word for word in lexicons["penalty_keywords"]["hit"] if word in text]
        clear = [word for word in lexicons["penalty_keywords"]["clear"] if word in text]
        if str(value or "") == "hit":
            if hit:
                return MatchResult(-1, "support", _sentence_with(text, hit[0]), hit[0])
            if clear:
                return MatchResult(-1, "refute", _sentence_with(text, clear[0]), "clear")
        elif str(value or "") == "clear":
            if clear:
                return MatchResult(-1, "support", _sentence_with(text, clear[0]), "clear")
            if hit:
                return MatchResult(-1, "refute", _sentence_with(text, hit[0]), "hit")
        return MatchResult(-1, "unrelated")

    if field == "hours":
        claim_text = claim.text
        if "周一" in claim_text and ("闭店" in claim_text or "休息" in claim_text):
            windows = re.findall(r"周一[^。！？!?；;]{0,10}", text)
            support = any(
                any(word in window for word in ("闭店", "休息日", "不营业"))
                or ("休息" in window and "不休息" not in window)
                for window in windows
            )
            if support:
                return MatchResult(-1, "support", _sentence_with(text, "周一"), "monday_closed")
            refute = any("营业" in window and "不营业" not in window for window in windows)
            if refute:
                return MatchResult(-1, "refute", _sentence_with(text, "周一"), "monday_open")
        return MatchResult(-1, "unrelated")

    if field == "license":
        if any(word in text for word in ("食品经营许可证", "许可证", "资质", "备案")):
            if any(word in text for word in ("无证", "未取得", "注销")):
                return MatchResult(-1, "refute", _sentence_with(text, "无证") or _sentence_with(text, "未取得"), "missing")
            return MatchResult(-1, "support", _sentence_with(text, "许可证") or _sentence_with(text, "资质"), "present")
        return MatchResult(-1, "unrelated")

    if field == "reservation":
        if any(word in text for word in ("预约", "限流", "售罄", "满员")):
            return MatchResult(-1, "support", _sentence_with(text, "预约") or _sentence_with(text, "限流"), "needed")
        return MatchResult(-1, "unrelated")

    if field == "address":
        target = str(value or "")
        if target and target in text:
            return MatchResult(-1, "support", _sentence_with(text, target[:12]), target)
        return MatchResult(-1, "unrelated")

    if field == "ad_disclosure":
        lexicons = _lexicons()
        if any(word in text for word in lexicons["cta_phrases"]):
            return MatchResult(-1, "support", _sentence_with(text, "点击") or _sentence_with(text, "团购"), "cta")
        return MatchResult(-1, "unrelated")

    # Unknown fields have no deterministic matcher. "unknown" means "not
    # judged", which is honest; "unrelated" would assert evidence of absence.
    return MatchResult(-1, "unknown")


def _validate_quote(quote: str, page: SearchPage) -> tuple[bool, str]:
    if not quote:
        return False, ""
    source = _normalize_quote(page.text())
    candidate = _normalize_quote(quote)
    if candidate and candidate in source:
        return True, quote
    return False, ""


async def _match_batch(
    llm: Any,
    claim: Claim,
    pages: list[SearchPage],
    offset: int,
) -> list[MatchResult]:
    evidence_payload = [
        {
            "evidence_id": f"e{index}",
            "title": page.title,
            "site": page.site,
            "date": page.date,
            "passage": page.passage or page.content[:2000] or page.title,
            "content_excerpt": page.content[:2500] if page.content else "",
        }
        for index, page in enumerate(pages)
    ]
    payload = {
        "claim": {"text": claim.text, "field": claim.field, "value": claim.value},
        "evidence": evidence_payload,
    }
    try:
        data = await llm.json("match_evidence", payload, SYSTEM_PROMPT)
    except Exception as exc:
        event(
            logger,
            "matching.fallback",
            level=logging.WARNING,
            offset=offset,
            batch=len(pages),
            error=f"{type(exc).__name__}: {str(exc)[:200]}",
        )
        return [heuristic_match(claim, page) for page in pages]
    if not isinstance(data, dict):
        event(
            logger,
            "matching.fallback",
            level=logging.WARNING,
            offset=offset,
            batch=len(pages),
            error="model did not return an object",
        )
        return [heuristic_match(claim, page) for page in pages]
    raw_matches = {
        str(item.get("evidence_id")): item
        for item in data.get("matches") or []
        if isinstance(item, dict)
    }
    results: list[MatchResult] = []
    for index, page in enumerate(pages):
        global_index = offset + index
        item = raw_matches.get(f"e{index}")
        if not item:
            results.append(
                MatchResult(global_index, "unknown", reason="missing from model output")
            )
            continue
        relation = str(item.get("relation") or "unknown")
        if relation not in {"support", "refute", "unrelated", "unknown"}:
            relation = "unknown"
        quote = str(item.get("quote") or "")
        valid, clean_quote = _validate_quote(quote, page)
        if relation in {"support", "refute"} and not valid:
            results.append(
                MatchResult(
                    page_index=global_index,
                    relation="unrelated",
                    quote="",
                    observed_value=item.get("observed_value"),
                    reason="quote rejected: not found in retrieved text",
                    quote_rejected=True,
                )
            )
            continue
        results.append(
            MatchResult(
                page_index=global_index,
                relation=relation,
                quote=clean_quote if valid else "",
                observed_value=(str(item.get("observed_value")) if item.get("observed_value") is not None else None),
                reason=str(item.get("reason") or ""),
            )
        )
    return results


async def match_evidence(llm: Any | None, claim: Claim, pages: list[SearchPage]) -> list[MatchResult]:
    if not pages:
        return []
    if llm is None:
        return [heuristic_match(claim, page) for page in pages]
    results: list[MatchResult] = []
    for offset in range(0, len(pages), BATCH_SIZE):
        batch = pages[offset : offset + BATCH_SIZE]
        event(logger, "matching.batch", offset=offset, batch=len(batch), total=len(pages))
        results.extend(await _match_batch(llm, claim, batch, offset))
    return results
