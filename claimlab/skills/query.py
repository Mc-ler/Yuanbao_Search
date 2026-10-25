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
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit

from ..config import CONFIG_DIR
from ..contracts import Claim, QueryPlan, Requirement, make_id, normalize_cnt
from ..logging import event

logger = logging.getLogger("claimlab.query")

# SearchPro treats ``Site`` as an exact indexed host: ``www.stats.gov.cn``
# returns pages while ``stats.gov.cn`` / ``gov.cn`` silently return zero.
# Only this allowlist (plus exact ``www.*.gov.cn`` hosts) may reach the API.
SITE_ALLOWLIST = {
    "www.stats.gov.cn",
    "www.gov.cn",
    "www.ncha.gov.cn",
    "www.mohurd.gov.cn",
    "www.shaanxi.gov.cn",
    "www.xa.gov.cn",
    "www.beijing.gov.cn",
    "www.shanghai.gov.cn",
    "www.mct.gov.cn",
    "www.samr.gov.cn",
    "www.court.gov.cn",
    "www.creditchina.gov.cn",
    "www.12315.cn",
    "www.ndrc.gov.cn",
    "www.mwr.gov.cn",
    "www.moe.gov.cn",
    "www.mot.gov.cn",
    "www.miit.gov.cn",
    "www.nhc.gov.cn",
    "www.mca.gov.cn",
    "www.mof.gov.cn",
    "www.pbc.gov.cn",
    "www.customs.gov.cn",
    "www.cnipa.gov.cn",
    "www.people.com.cn",
    "www.xinhuanet.com",
    "www.news.cn",
    "www.cctv.com",
    "www.cnr.cn",
    "www.thepaper.cn",
    "www.caixin.com",
    "www.jiemian.com",
    "www.bjnews.com.cn",
    "www.chinanews.com.cn",
    "www.gmw.cn",
    "www.youth.cn",
    "www.ce.cn",
    "www.chinadaily.com.cn",
    "www.stdaily.com",
    "163.com",
    "qq.com",
    "news.qq.com",
    "baike.baidu.com",
    "dianping.com",
    "amap.com",
    "ctrip.com",
    "mp.weixin.qq.com",
}

_SITE_OPERATOR_RE = re.compile(r"(?i)(?:^|\s)site:\S+\s*")


def normalize_site(value: Any) -> str | None:
    """Return an exact indexed host, or None for apex/unknown/invalid values."""
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    host = (urlsplit(raw).hostname or "") if "://" in raw else raw.split("/")[0].strip()
    host = host.strip(".")
    if not host:
        return None
    if host in SITE_ALLOWLIST:
        return host
    if host.startswith("www.") and host.endswith(".gov.cn"):
        return host
    return None


def strip_site_operator(query: str) -> str:
    """Remove ``site:host`` tokens; SearchPro ignores the operator and treats it
    as plain text, which silently lowers relevance."""
    return re.sub(r"\s+", " ", _SITE_OPERATOR_RE.sub(" ", str(query or ""))).strip()


@lru_cache(maxsize=1)
def load_queries(path: Path | None = None) -> dict:
    source = path or (CONFIG_DIR / "queries.json")
    return json.loads(source.read_text(encoding="utf-8"))


def _fill(template: str, focus: str, target_text: str, terms: str = "") -> str:
    """Fill a query template.

    Only three placeholders exist: {focus} (derived research object),
    {claim} (legacy assertion text) and {terms} (search terms). There is no
    {subject}/{city}: the public API no longer accepts them and research never
    injects them.
    """
    return (
        template.replace("{focus}", focus)
        .replace("{claim}", target_text)
        .replace("{terms}", terms)
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


def _clean_terms(
    terms: list[str],
    focus: str,
    template: str = "",
) -> list[str]:
    """Drop subject/field words already supplied by the template.

    This prevents queries such as ``国家统计局 国家统计局 ...`` and
    ``西安市 通知 通知`` without dropping year/number/metric terms.
    """
    cleaned: list[str] = []
    for term in terms:
        term = term.strip()
        if not term:
            continue
        if term == focus:
            continue
        if focus and term in focus:
            continue
        if template and term in template:
            continue
        if term not in cleaned:
            cleaned.append(term)
    return cleaned


OFFICIAL_FIELDS = {
    "business_status",
    "penalty",
    "license",
    "statistics_source",
    "statistics_method",
    "statistics_release",
    "statistics_value",
    "policy",
    "scenic_history",
    "scenic_explanation",
    "heritage_status",
    "traffic_restriction",
    "ev_license",
    "ev_restriction",
    "municipal_notice",
    "municipal_effective",
}


def plan_queries(
    target: Claim | Requirement,
    focus: str | None = None,
    round_no: int = 0,
    used: set[tuple[str, str | None, str | None]] | None = None,
    max_plans: int = 4,
) -> list[QueryPlan]:
    config = load_queries()
    field = getattr(target, "field", "unknown") or "unknown"
    field_cfg = config["fields"].get(field) or config["fields"]["unknown"]
    target_text = str(getattr(target, "text", "") or "").strip()
    focus_value = (focus or getattr(target, "focus", None) or target_text).strip()
    search_terms = [str(item).strip() for item in (getattr(target, "search_terms", []) or []) if str(item).strip()]
    terms_list = _clean_terms(search_terms, focus_value)
    claim_id = str(getattr(target, "claim_id", "") or "")
    requirement_id = str(getattr(target, "requirement_id", "") or "")
    target_id = claim_id or requirement_id
    source_preference = getattr(target, "source_preference", None)
    variants = field_cfg.get("variants") or ["{focus}"]
    precise = dict(field_cfg.get("precise") or {})
    precise_site = normalize_site(precise.get("site"))
    if source_preference and not precise_site and not precise.get("industry"):
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
        cnt: int = 10,
    ) -> QueryPlan:
        terms_text = " ".join(_clean_terms(terms_list, focus_value, template))
        if not terms_text and "{focus}" not in template:
            terms_text = target_text
        query = _fill(template, focus_value, target_text, terms_text)
        return QueryPlan(
            plan_id=make_id("q", target_id, round_no, query, site, industry),
            claim_id=claim_id,
            requirement_id=requirement_id,
            query=query,
            mode=0,
            site=site,
            cnt=cnt,
            industry=industry,
            freshness=freshness,
            precision=precision,  # type: ignore[arg-type]
            round=round_no,
            strategy=strategy,
        )

    if round_no == 0:
        if field in OFFICIAL_FIELDS:
            candidates = [
                make(
                    variants[0],
                    site=precise_site,
                    industry=precise.get("industry"),
                    precision="precise",
                    strategy="定向检索",
                ),
                make(
                    variants[1] if len(variants) > 1 else variants[0],
                    precision="fuzzy",
                    strategy="目标词扩展",
                ),
                make(variants[2] if len(variants) > 2 else variants[0], precision="fuzzy", strategy="同义改写"),
            ]
            if len(variants) > 3:
                candidates.append(make(variants[3], precision="fuzzy", strategy="同义改写"))
        else:
            candidates = [
                make(variants[0], precision="fuzzy", strategy="裸查询"),
                make(
                    variants[1] if len(variants) > 1 else variants[0],
                    site=precise_site,
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
        if precise_site:
            alt_industry = "gov" if field in OFFICIAL_FIELDS else "news"
            candidates = [
                make(variants[0], industry=alt_industry, precision="precise", strategy="换 Industry"),
                make(variants[-1], site=precise_site, precision="precise", strategy="换表述 + Site"),
            ]
        elif field in OFFICIAL_FIELDS:
            candidates = [
                make(variants[0], industry="gov", precision="precise", strategy="换 Industry"),
                make(variants[-1], site="www.gov.cn", precision="precise", strategy="换表述 + Site"),
            ]
        else:
            alt_site = "dianping.com" if field in {"price", "hours"} else "ctrip.com"
            candidates = [
                make(variants[0], site=alt_site, precision="precise", strategy="换 Site"),
                make(variants[-1], industry="gov", precision="precise", strategy="换表述 + Industry"),
            ]

    if round_no == 0:
        # Generic facets keep every field from collapsing into only three
        # near-identical queries. They are lower precision than the field
        # templates, so they are appended after the primary candidates.
        for suffix in ("官方 原文", "数据 统计", "反驳 争议", "最新"):
            candidates.append(
                make(
                    "{focus} {terms} " + suffix,
                    precision="fuzzy",
                    strategy="通用facet/" + suffix,
                )
            )
    filtered = [plan for plan in candidates if plan.query and plan_key(plan) not in used]
    return _dedupe(filtered)[:max_plans]


def plan_requirement_queries(
    requirement: Requirement,
    round_no: int = 0,
    used: set[tuple[str, str | None, str | None]] | None = None,
    max_plans: int = 4,
) -> list[QueryPlan]:
    """Stable entry point for the downstream query interface."""
    return plan_queries(
        requirement,
        round_no=round_no,
        used=used,
        max_plans=max_plans,
    )


def _target_values(
    target: Requirement,
) -> tuple[str, str, list[str]]:
    text = str(getattr(target, "text", "") or "").strip()
    focus = str(getattr(target, "focus", None) or text).strip()
    terms = [
        str(item).strip()
        for item in (getattr(target, "search_terms", []) or [])
        if str(item).strip()
    ]
    return focus, text, terms


def plan_fallback_queries(
    requirement: Requirement,
    used: set[tuple[str, str | None, str | None]] | None = None,
    max_plans: int = 1,
) -> list[QueryPlan]:
    """B/C fallback: no Site/Industry, target terms only; never duplicate."""
    config = load_queries()
    field = requirement.field or "unknown"
    field_cfg = config["fields"].get(field) or config["fields"]["unknown"]
    focus, text, terms = _target_values(requirement)
    variants = field_cfg.get("variants") or ["{focus}"]
    used = used or set()
    plans: list[QueryPlan] = []
    for template in variants:
        terms_text = " ".join(_clean_terms(terms, focus, template)) or text
        query = _fill(template, focus, text, terms_text)
        if not query:
            continue
        plan = QueryPlan(
            plan_id=make_id("q", requirement.requirement_id, "fallback", query),
            claim_id="",
            requirement_id=requirement.requirement_id,
            query=query,
            freshness=field_cfg.get("freshness"),
            precision="fuzzy",
            strategy="B/C降级",
        )
        if plan_key(plan) in used:
            continue
        plans.append(plan)
        if len(plans) >= max_plans:
            break
    return _dedupe(plans)


def plan_requery_queries(
    requirement: Requirement,
    used: set[tuple[str, str | None, str | None]] | None = None,
    max_plans: int = 1,
) -> list[QueryPlan]:
    """One alternate query after a zero/low-reliability result; no duplicate."""
    config = load_queries()
    field = requirement.field or "unknown"
    field_cfg = config["fields"].get(field) or config["fields"]["unknown"]
    focus, text, terms = _target_values(requirement)
    variants = list(reversed(field_cfg.get("variants") or ["{focus}"]))
    used = used or set()
    plans: list[QueryPlan] = []
    for template in variants:
        terms_text = " ".join(_clean_terms(terms, focus, template)) or text
        query = _fill(template, focus, text, terms_text)
        if not query:
            continue
        plan = QueryPlan(
            plan_id=make_id("q", requirement.requirement_id, "requery", query),
            claim_id="",
            requirement_id=requirement.requirement_id,
            query=query,
            industry="gov" if field in OFFICIAL_FIELDS else None,
            freshness=field_cfg.get("freshness"),
            precision="precise" if field in OFFICIAL_FIELDS else "fuzzy",
            strategy="再查询",
        )
        if plan_key(plan) in used:
            continue
        plans.append(plan)
        if len(plans) >= max_plans:
            break
    return _dedupe(plans)

def plan_time_series_queries(
    target: Claim | Requirement,
    focus: str | None = None,
    windows: list[str] | None = None,
    years: list[str] | None = None,
    used: set[tuple[str, str | None, str | None]] | None = None,
    max_plans: int = 8,
) -> list[QueryPlan]:
    """Sweep Freshness windows / year terms to expand evidence coverage.

    Each plan gets a distinct Freshness window (and an optional year prepended
    to the query text) so successive queries hit different time slices instead
    of returning the same top pages. Used by the broad-search script.
    """
    config = load_queries()
    field = getattr(target, "field", "unknown") or "unknown"
    field_cfg = config["fields"].get(field) or config["fields"]["unknown"]
    target_text = str(getattr(target, "text", "") or "").strip()
    focus_value = (focus or getattr(target, "focus", None) or target_text).strip()
    terms = [str(x).strip() for x in (getattr(target, "search_terms", []) or []) if str(x).strip()]
    variants = field_cfg.get("variants") or ["{focus}"]
    windows = [str(w) for w in (windows or ["d30", "m3", "m6", "y1", "y2", "y5"])]
    years = [str(y) for y in (years or []) if str(y).strip()]
    used = used or set()
    target_id = str(getattr(target, "claim_id", "") or getattr(target, "requirement_id", "") or "")
    plans: list[QueryPlan] = []
    seen: set[tuple] = set()

    def ts_key(plan: QueryPlan) -> tuple:
        return (plan.query, plan.site, plan.industry, plan.freshness)

    for window in windows:
        for year in years or [None]:
            for template in variants:
                terms_text = " ".join(_clean_terms(terms, focus_value, template)) or target_text
                query = _fill(template, focus_value, target_text, terms_text)
                if year and str(year) not in query:
                    query = f"{year} {query}"
                if not query:
                    continue
                plan = QueryPlan(
                    plan_id=make_id("q", target_id, "ts", window, year or "", query),
                    claim_id=str(getattr(target, "claim_id", "") or ""),
                    requirement_id=str(getattr(target, "requirement_id", "") or ""),
                    query=query,
                    mode=0,
                    cnt=10,
                    industry="gov" if field in OFFICIAL_FIELDS else None,
                    freshness=window,
                    precision="precise" if field in OFFICIAL_FIELDS else "fuzzy",
                    strategy=f"时间序列/{window}" + (f"/{year}" if year else ""),
                )
                if ts_key(plan) in seen or plan_key(plan) in used:
                    continue
                seen.add(ts_key(plan))
                plans.append(plan)
                if len(plans) >= max_plans:
                    return plans
    return plans

_ALLOWED_INDUSTRY = {"gov", "news", "acad"}
_ALLOWED_FRESHNESS = {"d30", "m3", "m6", "y1", "y2", "y5"}


def coerce_llm_queries(
    data: Any,
    requirement: Requirement,
) -> list[QueryPlan]:
    """Validate/coerce LLM-built SearchPro request fields into QueryPlans."""
    if not isinstance(data, dict):
        return []
    raw_items = data.get("queries")
    if not isinstance(raw_items, list):
        return []
    plans: list[QueryPlan] = []
    for index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            continue
        query = strip_site_operator(str(item.get("query") or ""))
        if not query:
            continue
        # A5/B: never forward an apex or unknown host. SearchPro fails closed
        # with HTTP 200 + zero pages, so a bad Site costs a full query.
        site = normalize_site(item.get("site"))
        industry = str(item.get("industry") or "").strip() or None
        if industry and industry not in _ALLOWED_INDUSTRY:
            industry = None
        freshness = str(item.get("freshness") or "").strip() or None
        if freshness and freshness not in _ALLOWED_FRESHNESS:
            freshness = None
        try:
            mode = int(item.get("mode") or 0)
        except (TypeError, ValueError):
            mode = 0
        cnt = normalize_cnt(item.get("cnt", 10))
        precision = "precise" if (site or industry) else "fuzzy"
        plans.append(
            QueryPlan(
                plan_id=make_id("q", requirement.requirement_id, "llm", index, query),
                claim_id="",
                requirement_id=requirement.requirement_id,
                query=query,
                mode=mode,
                site=site,
                cnt=cnt,
                industry=industry,
                freshness=freshness,
                precision=precision,
                round=0,
                strategy="LLM构造",
            )
        )
    return plans


async def build_queries_llm(
    llm: Any,
    requirement: Requirement,
) -> list[QueryPlan]:
    """LLM constructs SearchPro request fields; empty list on any failure."""
    if llm is None:
        return []
    prompt = (
        "你是查询构造器。给定一个可检索需求，为元宝 SearchPro 构造请求字段，只输出 JSON。\n"
        "输出格式：{\"queries\":[{\"query\":\"...\",\"site\":null,\"industry\":null,\"freshness\":null,\"mode\":0,\"cnt\":10}]}\n"
        "规则：\n"
        "1. 生成 4-6 条查询，每条 query 用自然语言写全（把主体、城市、年份、指标都写进 query），可独立命中网页；至少包含实体查询、官方原文、数据/统计或历史、反证/争议、时间窗口五个角度中的三个。\n"
        "2. site 默认填 null；只有确切知道站点索引 host 时才填（必须带 www 前缀，例如 www.stats.gov.cn、www.xa.gov.cn），不要写 site: 运算符。industry 取 gov/news/acad；freshness 取 d30/m3/m6/y1/y2/y5；不需要的字段填 null，cnt 默认 10。\n"
        "3. 只输出 JSON，不要解释。"
    )
    payload = {
        "text": requirement.text,
        "field": requirement.field,
        "source_preference": requirement.source_preference or "",
        "time_window": requirement.time_window or "",
        "search_terms": requirement.search_terms or [],
    }
    try:
        data = await llm.json("build_queries", payload, prompt)
    except Exception as exc:
        event(
            logger,
            "queries.fallback",
            level=logging.WARNING,
            method="template",
            reason=f"{type(exc).__name__}: {str(exc)[:200]}",
        )
        return []
    plans = coerce_llm_queries(data, requirement)
    if not plans:
        event(
            logger,
            "queries.fallback",
            level=logging.WARNING,
            method="template",
            reason="invalid or empty queries JSON",
        )
    return plans
