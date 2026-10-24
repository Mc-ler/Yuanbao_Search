"""A-E source grading by domain, Industry hint and evidence age.

The grade is a rule, not a model judgement: it must be explainable on stage
and stable across runs. `authority_level` is intentionally not used because
the standard edition does not return it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config import CONFIG_DIR
from ..contracts import Grade, SearchPage

GRADE_ORDER: dict[str, int] = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}
DOWNGRADE = {"A": "B", "B": "C", "C": "D", "D": "E", "E": "E"}

# Historical/heritage facts and annual statistics are not "stale" on the same
# 365-day clock as a municipal notice or a restaurant's opening hours.
FIELD_AGE_DAYS = {
    "statistics_source": 730,
    "statistics_method": 730,
    "statistics_release": 730,
    "scenic_history": 3650,
    "scenic_explanation": 3650,
    "heritage_status": 3650,
}


@lru_cache(maxsize=1)
def load_domains(path: Path | None = None) -> dict[str, Any]:
    source = path or (CONFIG_DIR / "domains.json")
    return json.loads(source.read_text(encoding="utf-8"))


@dataclass
class GradeResult:
    grade: Grade
    reason: str
    verifiable: str
    older: bool = False


def _domain_match(host: str, suffixes: list[str], domains: list[str]) -> bool:
    for candidate in list(suffixes) + list(domains):
        candidate = candidate.lower()
        if host == candidate or host.endswith("." + candidate):
            return True
    return False


def _base_grade(host: str) -> tuple[Grade, str]:
    config = load_domains()
    if not host:
        return "D", "域名缺失，按自媒体处理"
    if host == "gov.cn" or host.endswith(".gov.cn"):
        return "A", "gov.cn 域名"
    best: tuple[int, str, str] | None = None
    for grade in ("A", "B", "C", "D", "E"):
        block = config["grades"][grade]
        for suffix in list(block.get("suffixes") or []) + list(block.get("domains") or []):
            suffix = suffix.lower()
            if host == suffix or host.endswith("." + suffix):
                candidate = (len(suffix), grade, suffix)
                if best is None or candidate[0] > best[0]:
                    best = candidate
    if best is not None:
        return best[1], f"域名匹配 {best[2]}"  # type: ignore[return-value]
    return config.get("default_grade", "D"), "未知域名，默认按自媒体处理"


def grade_page(page: SearchPage, industry: str | None = None, field: str | None = None) -> GradeResult:
    host = (page.domain or "").lower()
    grade, reason = _base_grade(host)
    config = load_domains()
    # Industry is a retrieval filter, not a grading signal. A page is graded
    # by where it is published and how old it is; otherwise a UGC page found
    # through Industry=news would be silently promoted to B.
    if industry:
        reason = f"{reason}；检索过滤 Industry={industry}，不改变来源等级"
    older = False
    limit = FIELD_AGE_DAYS.get(field or "", int(config.get("age_downgrade_days", 365)))
    if page.age_days is not None and page.age_days > limit:
        downgraded = DOWNGRADE[grade]
        if downgraded != grade:
            reason = f"{reason}；证据超过 {limit} 天，降一级"
        grade = downgraded
        older = True
    verifiable = config["grades"][grade].get("verifiable", "需人工")
    return GradeResult(grade=grade, reason=reason, verifiable=verifiable, older=older)


def grade_pages(
    pages: list[SearchPage],
    industry: str | None = None,
    field: str | None = None,
) -> list[GradeResult]:
    return [grade_page(page, industry, field) for page in pages]


def grade_rank(grade: str) -> int:
    return GRADE_ORDER.get(grade, 9)


def is_at_least(grade: str, threshold: str) -> bool:
    return grade_rank(grade) <= grade_rank(threshold)
