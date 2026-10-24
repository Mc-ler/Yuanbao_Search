"""Citation numbering and validation.

The model may cite [n], but the program owns the citation set. Out-of-range
references are marked, never silently trusted, and the UI only links valid
numbers.
"""

from __future__ import annotations

import re
from typing import Any

_REF_RE = re.compile(r"\[(\d{1,3})\]")


def extract_refs(text: str) -> list[int]:
    return [int(match.group(1)) for match in _REF_RE.finditer(text or "")]


def validate_citations(text: str, citations: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    """Return text with invalid [n] marked and a list of issues."""
    valid = {int(item.get("n") or 0) for item in citations if item.get("n")}
    issues: list[dict[str, Any]] = []
    seen: set[int] = set()

    def replace(match: re.Match[str]) -> str:
        number = int(match.group(1))
        if number in valid:
            return match.group(0)
        if number not in seen:
            issues.append({"n": number, "reason": "out_of_range"})
            seen.add(number)
        return f"[{number}?]"

    cleaned = _REF_RE.sub(replace, text or "")
    if citations and not extract_refs(cleaned):
        issues.append({"n": 0, "reason": "no_valid_citation"})
    return cleaned, issues


def citation_numbers(text: str, citations: list[dict[str, Any]]) -> list[int]:
    valid = {int(item.get("n") or 0) for item in citations if item.get("n")}
    return sorted({number for number in extract_refs(text) if number in valid})
