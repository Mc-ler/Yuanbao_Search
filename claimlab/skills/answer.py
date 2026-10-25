"""Conclusion + numbered-citation answer generation (no-fabrication).

The research answer stage deliberately receives citation metadata and optional
page screenshots, not the full retrieved passage. Screenshots are attached as
vision inputs; the model must say "未获证据" when it cannot read one.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .citations import citation_numbers, validate_citations
from ..logging import event
from .recency import (
    age_days,
    now_cst,
    parse_published,
    sort_sources,
    stale_evidence,
)

logger = logging.getLogger("claimlab.answer")

NO_RESULT_TEXT = "不知道：当前没有检索到可核验的结果，无法确定。"

SYSTEM_PROMPT = """你是研究综述生成器。给定一个研究问题、一组带编号的 A/B/C/D 来源元数据、内容节选和可选网页截图，产出可核验的研究综述。只输出 JSON。
规则：
1. 只依据给定来源元数据、内容节选和截图作答；禁止编造来源里没有的出处、日期、文号、机构、人物、数字。
2. 每个事实句后带 [n] 引用编号；没有来源支撑的句子必须写（未获证据），并明确说“不知道/没有结果/无法确定”，不得猜测。
3. 截图是来源 [n] 的页面截图；截图看不清、被登录墙挡住或与问题无关时，写（未获证据），不要猜。
4. 这是研究综述，不是 R1–R5 判定；不要输出“成立/不成立/已证实”等判定词，除非来源本身明确写了。
5. 综述至少包含：结论（2–4 句）、主要依据（2–4 点，逐点带 [n]）、证据缺口；不要只列标题或写“尚无模型综述”。
6. 优先使用 A/B 来源的内容节选组织具体表述；C/D 来源只能作为弱补充。不能把“没有检索到”写成“不存在”。
7. 必须先看给定的当前日期与时效信息；这些是内部字段，回答里不要出现字段名或 true/false。用户问“今天/目前/最新/最近/本周/今年”时，只按当前日期之前且落在时效窗口内的来源回答；如果最新来源已过期，必须写“最新来源截至 YYYY-MM-DD，无法确定当前状态”，不能拿旧数据冒充当前。
8. 相对时间按给定当前日期解析；用“截至 2026年10月25日”“距今 86 天”这类自然语言写出来源日期与当前日期的差距。新旧来源冲突时，分别列出日期、口径和适用范围，不能只挑支持结论的一条。
9. claims 必须是可核对的 claim–quote–source 结构：每条 quote 必须是来源中的原文片段，不能改写；找不到原文时 claims 留空并写证据缺口，不要编造 quote。
10. text、uncertainty、time_note 必须是自然语言；禁止出现 as_of、time_context、stale、time_sensitive、freshness_days、latest_source_date、latest_source_age_days、has_dated_source 等内部字段名，禁止 JSON、对象字面量、键值对或统计字典（例如 {"refuted":2,"suspect":1}）。日期写成“2026年10月25日”或“2026-10-25”；引用只用 [n]。
输出：{"text":"...","claims":[{"text":"...","source_ids":[1],"quote":"来源原文片段","source_date":"YYYY-MM-DD","support":"direct|indirect|unverified"}],"citations_used":[1,2],"uncertainty":"...","time_note":"..."}
"""


def _sources_for(row: dict[str, Any]) -> list[dict[str, Any]]:
    return list(row.get("top_sources") or row.get("sources") or [])


def build_citations(
    rows: list[dict[str, Any]],
    time_sensitive: bool = False,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Dedupe sources, optionally order newest-first, then assign [1..N].

    ``limit=None`` keeps every top source (D3: breadth over token cost). The
    answer stage sees the full ledger instead of an arbitrary first three.
    """
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
    sources = [seen[key] for key in order]
    if time_sensitive:
        sources = sort_sources(sources, time_sensitive=True)
    if limit is not None:
        sources = sources[: max(1, limit)]
    citations: list[dict[str, Any]] = []
    for index, src in enumerate(sources, start=1):
        parsed = parse_published(src.get("date"))
        citations.append(
            {
                "n": index,
                "url": (src.get("url") or "").strip(),
                "title": src.get("title") or "",
                "domain": src.get("domain") or "",
                "grade": src.get("grade") or "",
                "date": src.get("date") or "",
                "published_at": parsed.isoformat() if parsed else "",
                "age_days": age_days(src.get("date")),
                "score": src.get("score"),
                "passage": src.get("passage") or "",
                "content_excerpt": src.get("content_excerpt") or "",
                "cluster_id": src.get("cluster_id") or "",
                "cluster_size": src.get("cluster_size") or 1,
                "cluster_domains": src.get("cluster_domains") or [],
            }
        )
    return citations


def _rule_answer(
    rows: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    time_context: dict[str, Any] | None = None,
) -> str:
    if not rows:
        return NO_RESULT_TEXT
    lines: list[str] = []
    context = time_context or {}
    if context.get("stale"):
        lines.append(
            "无法确定当前状态：最新来源日期为 "
            + str(context.get("latest_source_date") or "未知")
            + "，已超过本次时效窗口（"
            + str(context.get("freshness_days") or "?")
            + " 天）。以下仅为来源摘要。"
        )
    for row in rows:
        field = row.get("field_label") or row.get("field") or "综合"
        tier = row.get("tier") or "insufficient"
        if tier == "A/B":
            verdict = "A/B 级来源可读；以下为来源内容节选"
        elif tier == "B/C":
            verdict = "仅有 B/C 降级来源；以下为来源内容节选"
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
        # The rule fallback must still give source-grounded points; it never
        # pretends a model synthesis exists.
        excerpt_lines = []
        for src in srcs[:3]:
            excerpt = src.get("content_excerpt") or src.get("excerpt") or src.get("passage") or ""
            if excerpt:
                label = src.get("title") or src.get("domain") or "来源"
                excerpt_lines.append(str(label)[:48] + "：" + str(excerpt)[:260])
        if excerpt_lines and tier in {"A/B", "B/C"}:
            lines.append("  来源要点：")
            lines.extend("  - " + line for line in excerpt_lines)
    return "\n".join(lines)


def _evidence_text(
    citations: list[dict[str, Any]],
    as_of: str = "",
    time_context: dict[str, Any] | None = None,
) -> str:
    lines = ["当前日期（as-of）: " + (as_of or now_cst().date().isoformat())]
    context = time_context or {}
    if context:
        lines.append(
            "时效上下文: time_sensitive="
            + str(bool(context.get("time_sensitive")))
            + " latest_source_date=" + str(context.get("latest_source_date") or "未知")
            + " freshness_days=" + str(context.get("freshness_days") or "?")
            + " stale=" + str(bool(context.get("stale")))
        )
    for c in citations:
        lines.append(
            "[" + str(c["n"]) + "] (" + (c["grade"] or "?") + ") " + (c["title"] or "")
            + " — " + (c["domain"] or "") + " " + (c["date"] or "")
            + "\nURL: " + c["url"]
            + ("\n内容节选: " + str(c.get("content_excerpt") or "") if c.get("content_excerpt") else "")
        )
    return "\n".join(lines)


def _clean_model_text(text: Any) -> str:
    raw = str(text or "").strip()
    if not raw.startswith("{"):
        return raw
    match = re.search(r'"text"\s*:\s*"(.*?)(?<!\\)"', raw, re.S)
    if match:
        value = match.group(1)
        try:
            return str(json.loads('"' + value + '"')).strip()
        except json.JSONDecodeError:
            return value.replace("\\n", "\n").strip()
    marker = '"text":"'
    if marker in raw:
        value = raw.split(marker, 1)[1]
        return value.rsplit('"', 1)[0].replace("\\n", "\n").strip()
    return raw


def _date_cn(raw: str) -> str:
    match = re.match(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", raw or "")
    if not match:
        return raw
    year, month, day = match.groups()
    return f"{year}年{int(month)}月{int(day)}日"


def _naturalize_time_text(value: Any) -> str:
    """Turn leaked internal time fields into readable Chinese.

    The model sometimes copies prompt keys such as ``as_of`` / ``stale=false``
    into uncertainty or prose. The data stays machine-readable in
    ``time_context``; user-facing text must not expose those keys.
    """
    text = str(value or "")
    if not text:
        return ""
    text = re.sub(
        r"(?i)[\"'`]?as[_-]?of[\"'`]?\s*(?:为|是|[:：=])?\s*[\"'`]?(20\d{2}[-/]\d{1,2}[-/]\d{1,2})[\"'`]?",
        lambda match: "截至 " + _date_cn(match.group(1)),
        text,
    )
    text = re.sub(r"(?i)[\"'`]?as[_-]?of[\"'`]?", "当前日期", text)
    text = re.sub(r"(?i)[\"'`]?time_context[\"'`]?", "时效信息", text)
    text = re.sub(
        r"(?i)[\"'`]?time_sensitive[\"'`]?\s*(?:为|是|[:：=])?\s*[\"'`]?(true|false)",
        lambda match: "涉及时效" if match.group(1).lower() == "true" else "不涉及时效",
        text,
    )
    text = re.sub(
        r"(?i)[\"'`]?stale[\"'`]?\s*(?:为|是|[:：=])?\s*[\"'`]?(true|false)",
        lambda match: "来源已超出时效窗口" if match.group(1).lower() == "true" else "来源仍在时效窗口内",
        text,
    )
    text = re.sub(
        r"(?i)[\"'`]?freshness_days[\"'`]?\s*(?:为|是|[:：=])?\s*[\"'`]?(\d+)",
        r"时效窗口为 \1 天",
        text,
    )
    text = re.sub(
        r"(?i)[\"'`]?latest_source_date[\"'`]?\s*(?:为|是|[:：=])?\s*[\"'`]?(20\d{2}[-/]\d{1,2}[-/]\d{1,2})[\"'`]?",
        lambda match: "最新来源日期为 " + _date_cn(match.group(1)),
        text,
    )
    text = re.sub(r"(?i)[\"'`]?latest_source_date[\"'`]?", "最新来源日期", text)
    text = re.sub(
        r"(?i)[\"'`]?latest_source_age_days[\"'`]?\s*(?:为|是|[:：=])?\s*[\"'`]?(\d+)",
        r"最新来源距今 \1 天",
        text,
    )
    text = re.sub(
        r"(?i)[\"'`]?has_dated_source[\"'`]?\s*(?:为|是|[:：=])?\s*[\"'`]?(true|false)",
        lambda match: "有来源日期" if match.group(1).lower() == "true" else "无来源日期",
        text,
    )
    had_braces = "{" in text or "}" in text
    text = text.replace("{", "").replace("}", "")
    if had_braces:
        # A leaked dict survives as quotes/commas after key replacement.
        text = text.replace('"', "").replace("'", "").replace("`", "")
        text = re.sub(r"\s*,\s*", "，", text)
    text = re.sub(r"距\s+当前日期", "距当前日期", text)
    text = re.sub(r"^\s*[。；，、]+", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    for noise in ("。；", "；；", "；。", "。。"):
        text = text.replace(noise, noise[0])
    return text.strip()


def _join_clauses(left: str, right: str) -> str:
    left = str(left or "").strip().rstrip("。；; ")
    right = str(right or "").strip()
    if not left:
        return right
    if not right:
        return left
    return left + "；" + right


def _compact(text: Any) -> str:
    return re.sub(r"[\s，。！？；：、“”‘’（）()【】\[\]]+", "", str(text or "")).lower()


def _source_text(source: dict[str, Any]) -> str:
    return " ".join(
        str(source.get(key) or "")
        for key in ("content_excerpt", "passage", "content")
    )


def _normalize_claims(
    data: dict[str, Any],
    citations: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    claims: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    by_n = {int(item["n"]): item for item in citations}
    for raw in data.get("claims") or []:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "").strip()
        if not text:
            continue
        raw_ids = raw.get("source_ids")
        if not isinstance(raw_ids, list):
            raw_ids = [raw.get("source_id")] if raw.get("source_id") is not None else []
        ids: list[int] = []
        for value in raw_ids:
            try:
                number = int(value)
            except (TypeError, ValueError):
                continue
            if number in by_n and number not in ids:
                ids.append(number)
        quote = str(raw.get("quote") or "").strip()[:500]
        quote_valid = False
        if not quote:
            issues.append({"n": 0, "reason": "quote_missing", "claim": text[:120]})
        else:
            compact_quote = _compact(quote)
            for number in ids or list(by_n):
                if compact_quote and compact_quote in _compact(_source_text(by_n[number])):
                    quote_valid = True
                    if number not in ids:
                        ids.append(number)
                    break
            if not quote_valid:
                issues.append({"n": ids[0] if ids else 0, "reason": "quote_not_found", "claim": text[:120]})
        source_date = ""
        for number in ids:
            source_date = str(by_n[number].get("date") or "")
            if source_date:
                break
        support = str(raw.get("support") or "").strip().lower()
        if support not in {"direct", "indirect", "unverified"}:
            support = "direct" if quote_valid else "unverified"
        claims.append(
            {
                "text": text,
                "source_ids": ids,
                "quote": quote,
                "source_date": source_date,
                "support": support,
                "quote_valid": quote_valid,
            }
        )
    return claims, issues


def _claims_from_text(
    text: str,
    citations: list[dict[str, Any]],
    limit: int = 6,
) -> list[dict[str, Any]]:
    """Fallback claim mapping when the model returns prose without claims.

    The quote is copied verbatim from the cited source; support remains
    "unverified" because the quote-to-claim relation was not model-checked.
    """
    by_n = {int(item["n"]): item for item in citations}
    claims: list[dict[str, Any]] = []
    for sentence in re.split(r"(?<=[。！？!?\n])", text or ""):
        clean = sentence.strip()
        if not clean:
            continue
        refs = citation_numbers(clean, citations)
        if not refs:
            continue
        source = by_n[refs[0]]
        quote = str(source.get("content_excerpt") or source.get("passage") or "").strip()[:240]
        claims.append(
            {
                "text": clean,
                "source_ids": refs,
                "quote": quote,
                "source_date": str(source.get("date") or ""),
                "support": "unverified",
                "quote_valid": bool(quote),
            }
        )
        if len(claims) >= limit:
            break
    return claims


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
    *,
    claims: list[dict[str, Any]] | None = None,
    as_of: str = "",
    time_sensitive: bool = False,
    time_context: dict[str, Any] | None = None,
    degraded_reason: str = "",
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
        "claims": claims or [],
        "as_of": as_of,
        "time_sensitive": time_sensitive,
        "time_context": time_context or {},
        "degraded_reason": degraded_reason,
    }


async def build_answer(
    llm: Any,
    question: str,
    rows: list[dict[str, Any]],
    *,
    images: list[dict[str, Any]] | None = None,
    screenshots: dict[int, dict[str, Any]] | None = None,
    time_sensitive: bool = False,
    as_of: str = "",
) -> dict[str, Any]:
    as_of = as_of or now_cst().date().isoformat()
    citations = _merge_screenshot_meta(
        build_citations(rows, time_sensitive=time_sensitive), screenshots
    )
    time_context = stale_evidence(citations, question, parse_published(as_of))
    time_context["time_sensitive"] = time_sensitive
    time_context["as_of"] = as_of
    if not time_sensitive:
        time_context["stale"] = False
    if not citations:
        event(logger, "answer.fallback", level=logging.WARNING, reason="no_citations")
        return _response(
            NO_RESULT_TEXT,
            "rule",
            [],
            [],
            [],
            "无证据",
            as_of=as_of,
            time_sensitive=time_sensitive,
            time_context=time_context,
            degraded_reason="no_citations",
        )

    data = None
    if llm is not None:
        payload = {
            "question": question,
            "as_of": as_of,
            "time_sensitive": time_sensitive,
            "time_context": time_context,
            "evidence": _evidence_text(citations, as_of=as_of, time_context=time_context),
        }
        try:
            data = await llm.json("answer", payload, SYSTEM_PROMPT, images=images or None)
        except Exception as exc:
            logger.warning("answer.llm_error %s: %s", type(exc).__name__, str(exc)[:300])
            data = None
        if isinstance(data, dict):
            draft = str(data.get("text") or data.get("answer") or "").strip()
            _, draft_issues = validate_citations(draft, citations)
            if citations and any(item.get("reason") == "no_valid_citation" for item in draft_issues):
                # One bounded repair attempt. The model must cite source
                # numbers; the deterministic fallback below remains available.
                try:
                    repair = await llm.json(
                        "answer",
                        payload,
                        SYSTEM_PROMPT + "\n注意：必须使用 [1]、[2] 等来源编号逐句引用；没有引用会被视为无效。",
                        images=images or None,
                    )
                    if isinstance(repair, dict):
                        data = repair
                except Exception as exc:
                    logger.warning("answer.repair_error %s: %s", type(exc).__name__, str(exc)[:300])

    if llm is not None and (
        not isinstance(data, dict)
        or not str(data.get("text") or data.get("answer") or "").strip()
    ):
        # Some providers return an empty answer when the evidence block is
        # large. Retry once with the strongest three sources only; the full
        # citation list remains available for the report.
        compact = citations[:3]
        compact_payload = {
            "question": question,
            "as_of": as_of,
            "time_sensitive": time_sensitive,
            "time_context": time_context,
            "evidence": _evidence_text(compact, as_of=as_of, time_context=time_context),
        }
        try:
            data = await llm.json(
                "answer",
                compact_payload,
                SYSTEM_PROMPT + "\n证据较多时只依据前三条来源作答，不要返回空内容。",
                images=images or None,
            )
            logger.info("answer.compact_retry sources=%s", len(compact))
        except Exception as exc:
            logger.warning("answer.compact_error %s: %s", type(exc).__name__, str(exc)[:300])
            data = None

    if isinstance(data, dict) and (str(data.get("text") or data.get("answer") or "")).strip():
        text, issues = validate_citations(
            _naturalize_time_text(_clean_model_text(data.get("text") or data.get("answer"))),
            citations,
        )
        claims, claim_issues = _normalize_claims(data, citations)
        for claim in claims:
            claim["text"] = _naturalize_time_text(claim.get("text"))
        issues.extend(claim_issues)
        if not claims:
            claims = _claims_from_text(text, citations)
        valid_refs = citation_numbers(text, citations)
        if citations and not valid_refs:
            issues.append({"n": 0, "reason": "no_valid_citation"})
            logger.warning("answer.no_valid_citation sources=%s", len(citations))
            event(
                logger,
                "answer.fallback",
                level=logging.WARNING,
                reason="no_valid_citation",
                sources=len(citations),
            )
            fallback = _rule_answer(rows, citations, time_context)
            return _response(
                fallback,
                "rule",
                citations,
                [],
                issues,
                "模型未给出有效引用，已退回来源要点摘要",
                claims=[],
                as_of=as_of,
                time_sensitive=time_sensitive,
                time_context=time_context,
                degraded_reason="no_valid_citation",
            )
        used = [
            int(x)
            for x in (data.get("citations_used") or [])
            if isinstance(x, (int, float)) and 1 <= int(x) <= len(citations)
        ]
        uncertainty = _naturalize_time_text(str(data.get("uncertainty") or ""))
        if data.get("time_note"):
            uncertainty = _join_clauses(
                uncertainty, _naturalize_time_text(str(data["time_note"]))
            )
        if time_context.get("stale"):
            uncertainty = _join_clauses(
                uncertainty,
                "最新来源日期为 "
                + str(time_context.get("latest_source_date") or "未知")
                + "，已超出时效窗口",
            )
        return _response(
            text,
            "llm",
            citations,
            used or valid_refs,
            issues,
            uncertainty,
            claims=claims,
            as_of=as_of,
            time_sensitive=time_sensitive,
            time_context=time_context,
        )

    event(
        logger,
        "answer.fallback",
        level=logging.WARNING,
        reason="llm_unavailable_or_invalid_json",
        sources=len(citations),
    )
    return _response(
        _rule_answer(rows, citations, time_context),
        "rule",
        citations,
        [c["n"] for c in citations[:6]],
        [],
        "离线规则汇总，未经大模型逐句核验",
        claims=[],
        as_of=as_of,
        time_sensitive=time_sensitive,
        time_context=time_context,
        degraded_reason="llm_unavailable_or_invalid_json",
    )
