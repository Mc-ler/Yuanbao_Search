"""Recency helpers: parse dates once, sort sources consistently, detect stale evidence."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any

CST = timezone(timedelta(hours=8))

_TIME_MARKERS = (
    "今天", "今日", "目前", "现在", "当前", "最新", "最近", "近期",
    "本周", "这周", "本月", "这个月", "今年", "截至", "截止",
    "昨天", "明日", "明天", "下月", "下周", "刚才", "刚刚",
)
_TIME_QUESTION_MARKERS = (
    "什么时候", "何时", "哪天", "几号", "日期", "生效", "实施", "发布",
    "通车", "开学", "供暖", "停水", "停电", "天气",
)
_DATE_FORMATS = (
    "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日",
    "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y年%m月%d日 %H:%M",
    "%Y-%m", "%Y年%m月", "%Y",
)
_GRADE_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}


def now_cst() -> datetime:
    return datetime.now(CST)


def is_time_sensitive(text: str) -> bool:
    value = text or ""
    if any(marker in value for marker in _TIME_MARKERS):
        return True
    return any(marker in value for marker in _TIME_QUESTION_MARKERS)


def parse_published(value: Any) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def published_iso(value: Any) -> str:
    parsed = parse_published(value)
    return parsed.isoformat() if parsed else ""


def age_days(value: Any, as_of: date | None = None) -> int | None:
    parsed = parse_published(value)
    if parsed is None:
        return None
    return ((as_of or now_cst().date()) - parsed).days


def freshness_days(text: str) -> int:
    if any(marker in text for marker in ("今天", "今日", "刚才", "刚刚")):
        return 3
    if any(marker in text for marker in ("本周", "这周")):
        return 7
    if any(marker in text for marker in ("本月", "这个月", "目前", "现在", "当前", "最新", "最近", "近期")):
        return 31
    if "今年" in text:
        return 365
    return 31


def sort_sources(sources: list[dict[str, Any]], time_sensitive: bool) -> list[dict[str, Any]]:
    """Sort a source list and keep date-unknown items last."""
    def key(src: dict[str, Any]) -> tuple:
        parsed = parse_published(src.get("date"))
        missing = 0 if parsed else 1
        stamp = -parsed.toordinal() if parsed else 0
        grade = _GRADE_ORDER.get(str(src.get("grade") or ""), 9)
        score = -(float(src.get("score") or 0.0))
        if time_sensitive:
            return (missing, stamp, grade, score)
        return (grade, score, missing, stamp)

    return sorted(sources, key=key)


def latest_source_date(sources: list[dict[str, Any]]) -> str:
    parsed = [d for d in (parse_published(src.get("date")) for src in sources) if d]
    return max(parsed).isoformat() if parsed else ""


def stale_evidence(sources: list[dict[str, Any]], question: str, as_of: date | None = None) -> dict[str, Any]:
    latest = latest_source_date(sources)
    latest_age = age_days(latest, as_of) if latest else None
    threshold = freshness_days(question)
    return {
        "latest_source_date": latest,
        "latest_source_age_days": latest_age,
        "freshness_days": threshold,
        "stale": bool(latest_age is not None and latest_age > threshold),
        "has_dated_source": bool(latest),
    }


def date_text(value: Any) -> str:
    parsed = parse_published(value)
    if parsed:
        return parsed.isoformat()
    raw = str(value or "").strip()
    return re.sub(r"\s+", " ", raw)[:40]
