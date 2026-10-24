"""Small, deterministic excerpt selection for research evidence.

SearchPro usually returns a page-level content field in addition to a short
passage. The report does not need to send the complete page to the LLM; a
term-ranked excerpt is enough for grounded citation and keeps token usage low.
"""

from __future__ import annotations

import re
from typing import Any


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[。！？!?；;\n]+", text) if part.strip()]


def best_excerpt(page: Any, terms: list[str] | None = None, max_chars: int = 700) -> str:
    text = _clean(str(getattr(page, "content", "") or getattr(page, "passage", "") or ""))
    if not text:
        return _clean(str(getattr(page, "passage", "") or getattr(page, "title", "") or ""))[:max_chars]
    terms = [str(term).strip().lower() for term in (terms or []) if len(str(term).strip()) >= 2]
    scored: list[tuple[int, int, str]] = []
    for index, sentence in enumerate(_sentences(text)):
        lowered = sentence.lower()
        score = sum(1 for term in terms if term in lowered)
        if score:
            scored.append((score, -index, sentence))
    if scored:
        scored.sort(reverse=True)
        chosen = [item[2] for item in scored[:4]]
    else:
        chosen = _sentences(text)[:3]
    excerpt = "。".join(chosen).strip()
    if excerpt and not excerpt.endswith(("。", "！", "？", "!", "?")):
        excerpt += "。"
    return excerpt[:max_chars]


def content_chars(page: Any) -> int:
    return len(_clean(str(getattr(page, "content", "") or "")))
