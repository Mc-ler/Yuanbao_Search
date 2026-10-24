"""Turn a requirement (S1 output) into precise and fuzzy queries.

S1 is requirement decomposition, not claim extraction. The planner accepts both
the new :class:`Requirement` target and the legacy :class:`Claim` target so the
verification UI keeps working while the research/query interface uses
requirements directly.

Templates keep the program from drifting into "bare query" mode, which is the
most common failure of search-backed verification products. At least one query
per requirement must carry Site= or Industry=.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from ..config import CONFIG_DIR
from ..contracts import Claim, QueryPlan, Requirement, make_id


@lru_cache(maxsize=1)
def load_queries(path: Path | None = None) -> dict:
    source = path or (CONFIG_DIR / "queries.json")
    return json.loads(source.read_text(encoding="utf-8"))


def _fill(template: str, subject: str, city: str, target_text: str) -> str:
    return (
        template.replace("{subject}", subject)
        .replace("{city}", city)
        .replace("{claim}", target_text)
        .strip()
    )


def _dedupe(plans: Iterable[QueryPlan]) -> list[QueryPlan]:
    seen: set[tuple] = set()
    result: list[QueryPlan] = []
    for plan in plans:
        key = (plan.query, plan.site, plan.industry, plan.freshness, plan.precision)
        if key in seen:
            continue
        seen.add(key)
        result.append(plan)
    return result


def plan_key(plan: QueryPlan) -> tuple[str, str | None, str | None]:
    return (plan.query, plan.site, plan.industry)


OFFICIAL_FIELDS = {
    "business_status",
    "penalty",
    "license",
    "statistics_source",
    "statistics_method",
    "scenic_history",
    "scenic_explanation",
    "traffic_restriction",
    "ev_license",
    "municipal_notice",
}


def plan_queries(
    target: Claim | Requirement,
    subject: str | None = None,
    city: str | None = None,
    round_no: int = 0,
    used: set[tuple[str, str | None, str | None]] | None = None,
    max_plans: int = 4,
) -> list[QueryPlan]:
    config = load_queries()
    field = getattr(target, "field", "unknown") or "unknown"
    field_cfg = config["fields"].get(field) or config["fields"]["unknown"]
    default_city = config.get("default_city", "西安")
    city_value = city or getattr(target, "city", None) or default_city
    subject_value = (subject or getattr(target, "subject", None) or city_value or "").strip()
    target_text = str(getattr(target, "text", "") or "").strip()
    claim_id = str(getattr(target, "claim_id", "") or "")
    requirement_id = str(getattr(target, "requirement_id", "") or "")
    target_id = claim_id or requirement_id
    source_preference = getattr(target, "source_preference", None)
    variants = field_cfg.get("variants") or [f"{{subject}} {target_text}"]
    precise = dict(field_cfg.get("precise") or {})
    if source_preference and not precise.get("site") and not precise.get("industry"):
        precise["industry"] = source_preference
    target_window = getattr(target, "time_window", None)
    freshness = target_window if target_window and target_window != "12m" else field_cfg.get("freshness")
    used = used or set()

    def make(
        template: str,
        *,
        site: str | None = None,
        industry: str | None = None,
        precision: str,
        strategy: str,
    ) -> QueryPlan:
        query = _fill(template, subject_value, city_value, target_text)
        return QueryPlan(
            plan_id=make_id("q", target_id, round_no, query, site, industry),
            claim_id=claim_id,
            requirement_id=requirement_id,
            query=query,
            mode=0,
            site=site,
            cnt=10,
            industry=industry,
            freshness=freshness,
            precision=precision,  # type: ignore[arg-type]
            round=round_no,
            strategy=strategy,
        )

    if round_no == 0:
        candidates = [
            make(variants[0], precision="fuzzy", strategy="裸查询"),
            make(
                variants[1] if len(variants) > 1 else variants[0],
                site=precise.get("site"),
                industry=precise.get("industry"),
                precision="precise",
                strategy="定向检索",
            ),
            make(variants[2] if len(variants) > 2 else variants[0], precision="fuzzy", strategy="同义改写"),
        ]
        if len(variants) > 3:
            candidates.append(make(variants[3], precision="fuzzy", strategy="同义改写"))
    else:
        # A retry must change the strategy: swap the directed parameter and
        # use a different phrasing. Never re-run the same query.
        if precise.get("site"):
            alt_industry = "gov" if field in OFFICIAL_FIELDS else "news"
            candidates = [
                make(variants[0], industry=alt_industry, precision="precise", strategy="换 Industry"),
                make(variants[-1], site=precise.get("site"), precision="precise", strategy="换表述 + Site"),
            ]
        elif field in OFFICIAL_FIELDS:
            candidates = [
                make(variants[0], industry="gov", precision="precise", strategy="换 Industry"),
                make(variants[-1], site="gov.cn", precision="precise", strategy="换表述 + Site"),
            ]
        else:
            alt_site = "dianping.com" if field in {"price", "hours"} else "ctrip.com"
            candidates = [
                make(variants[0], site=alt_site, precision="precise", strategy="换 Site"),
                make(variants[-1], industry="gov", precision="precise", strategy="换表述 + Industry"),
            ]

    filtered = [plan for plan in candidates if plan.query and plan_key(plan) not in used]
    return _dedupe(filtered)[:max_plans]


def plan_requirement_queries(
    requirement: Requirement,
    subject: str | None = None,
    city: str | None = None,
    round_no: int = 0,
    used: set[tuple[str, str | None, str | None]] | None = None,
    max_plans: int = 4,
) -> list[QueryPlan]:
    """Stable entry point for the downstream query interface."""
    return plan_queries(
        requirement,
        subject=subject,
        city=city,
        round_no=round_no,
        used=used,
        max_plans=max_plans,
    )
