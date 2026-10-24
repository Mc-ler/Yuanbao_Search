"""Normalization of the Yuanbao Search (SearchPro) REST API response.

The REST API returns Pages as JSON *strings*; the Bearer example uses
`images` while the API reference uses `pics`. Everything funnels into a
normalized SearchBatch here.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit

from ..contracts import SearchBatch, SearchPage, SearchRequest, now_iso

_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")
_DATE_FORMATS = (
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d",
    "%Y-%m-%d",
    "%Y.%m.%d",
)


def strip_html(value: str | None) -> str:
    if not value:
        return ""
    return _SPACE_RE.sub(" ", _TAG_RE.sub(" ", value)).strip()


def domain_of(url: str) -> str:
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return ""
    return host.lower().removeprefix("www.")


def normalize_date(value: str | None) -> tuple[str | None, int | None]:
    if not value:
        return None, None
    raw = value.strip()
    parsed: date | None = None
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(raw, fmt).date()
            break
        except ValueError:
            continue
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError:
            return None, None
    age = (datetime.now().date() - parsed).days
    return parsed.isoformat(), age


def _loads_maybe_twice(value: Any) -> Any:
    obj = value
    for _ in range(2):
        if isinstance(obj, str):
            raw = obj.strip()
            if not raw:
                return None
            obj = json.loads(raw)
        else:
            break
    return obj


def parse_pages_field(value: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """Accept list/dict/str/JSON-string-array and return plain page dicts."""
    pages: list[dict[str, Any]] = []
    warnings: list[str] = []

    def consume(item: Any, depth: int = 0) -> None:
        if item is None or depth > 2:
            return
        if isinstance(item, dict):
            pages.append(item)
            return
        if isinstance(item, list):
            for sub in item:
                consume(sub, depth + 1)
            return
        if isinstance(item, str):
            try:
                parsed = _loads_maybe_twice(item)
            except (json.JSONDecodeError, TypeError):
                warnings.append("page item is not valid JSON")
                return
            if isinstance(parsed, (dict, list)):
                consume(parsed, depth + 1)
            else:
                warnings.append("page item is not an object")

    consume(value)
    return pages, warnings


def normalize_page(raw: dict[str, Any]) -> SearchPage:
    url = str(raw.get("url") or "").strip()
    title = strip_html(str(raw.get("title") or ""))
    passage = strip_html(str(raw.get("passage") or ""))
    content = strip_html(str(raw.get("content") or ""))
    pics_raw = raw.get("pics")
    if pics_raw is None:
        pics_raw = raw.get("images")
    pics: list[dict[str, Any]] = []
    if isinstance(pics_raw, list):
        for pic in pics_raw:
            if isinstance(pic, dict):
                pics.append(
                    {
                        "caption": str(pic.get("caption") or ""),
                        "origin_url": str(pic.get("origin_url") or ""),
                    }
                )
    date_value, age_days = normalize_date(raw.get("date"))
    score = raw.get("score")
    try:
        score_value = float(score) if score is not None else None
    except (TypeError, ValueError):
        score_value = None
    authority = raw.get("authority_level")
    try:
        authority_value = int(authority) if authority is not None else None
    except (TypeError, ValueError):
        authority_value = None
    if content and len(content) > len(passage):
        strength = "full-ish"
    elif passage:
        strength = "snippet"
    else:
        strength = "title"
    return SearchPage(
        title=title,
        url=url,
        domain=domain_of(url),
        site=str(raw.get("site") or "").strip(),
        date=date_value,
        age_days=age_days,
        passage=passage,
        content=content,
        score=score_value,
        pics=pics,
        favicon=str(raw.get("favicon") or ""),
        authority_level=authority_value,
        strength=strength,
    )


def normalize_api_response(
    payload: Any,
    provider: str = "api",
    latency_ms: float = 0.0,
    request: SearchRequest | None = None,
) -> SearchBatch:
    if not isinstance(payload, dict):
        return SearchBatch(
            provider=provider,
            latency_ms=latency_ms,
            error="unexpected response shape",
            error_kind="server",
            raw=payload,
            request=request,
        )
    body = payload.get("Response", payload)
    if not isinstance(body, dict):
        return SearchBatch(
            provider=provider,
            latency_ms=latency_ms,
            error="unexpected response shape",
            error_kind="server",
            raw=payload,
            request=request,
        )
    error = body.get("Error")
    if isinstance(error, dict):
        code = str(error.get("Code") or "error")
        message = str(error.get("Message") or "")
        return SearchBatch(
            provider=provider,
            request_id=str(body.get("RequestId") or ""),
            latency_ms=latency_ms,
            error=f"{code}: {message}".strip(": "),
            error_kind="auth" if code.lower() in {"unauthorizedoperation", "unauthorized", "invalidcredential", "invalidtoken"} else "server",
            raw=payload,
            request=request,
        )
    raw_pages, warnings = parse_pages_field(body.get("Pages"))
    pages = [normalize_page(item) for item in raw_pages]
    msg = str(body.get("Msg") or "").strip()
    if msg:
        warnings.append(msg)
    return SearchBatch(
        provider=provider,
        request_id=str(body.get("RequestId") or ""),
        version=str(body.get("Version") or ""),
        pages=pages,
        raw=payload,
        latency_ms=latency_ms,
        warnings=warnings,
        query=str(body.get("Query") or (request.query if request else "")),
        request=request,
    )


def normalized_now() -> str:
    return now_iso()
