"""Source-tier policy: A/B first, B/C fallback, then one requery.

This module does not perform network calls. It gives the eventual live runner a
single deterministic decision point, so fallback and requery behavior can be
tested without duplicating query strings.
"""

from __future__ import annotations

from ..contracts import Requirement, SearchPage
from .grading import grade_page


def is_relevant(page: SearchPage, requirement: Requirement | None = None) -> bool:
    if requirement is None or not requirement.search_terms:
        return True
    text = page.text().lower()
    terms = [term.lower() for term in requirement.search_terms if len(term.strip()) >= 2]
    return not terms or any(term in text for term in terms)


def source_tier(
    pages: list[SearchPage],
    industry: str | None = None,
    requirement: Requirement | None = None,
) -> str:
    relevant = [page for page in pages if is_relevant(page, requirement)]
    grades = [
        grade_page(page, industry, requirement.field if requirement else None).grade
        for page in relevant
    ]
    if any(grade in {"A", "B"} for grade in grades):
        return "A/B"
    if any(grade in {"B", "C"} for grade in grades):
        return "B/C"
    return "insufficient"


def next_action(tier: str, attempts: int, max_attempts: int = 2) -> str:
    """accept | requery | insufficient (relaxed: B/C is terminal).

    attempts counts actual search rounds already spent for this requirement.
    The caller must stay within its existing budget; this policy never increases
    the query allowance.
    """
    if tier in {"A/B", "B/C"}:
        return "accept"
    if attempts < max_attempts:
        return "requery"
    return "insufficient"
