"""S1 · 需求拆分 (requirement decomposition).

This module replaces assertion extraction in the query-construction path. It
turns a research question into 1–3 searchable Requirement units that are passed
directly to :func:`claimlab.skills.query.plan_requirement_queries`.

The legacy claim verifier still uses ``skills/extraction.py``; it is not the S1
entry point for the reporting/query interface.
"""

from __future__ import annotations

import re
from typing import Any

from ..contracts import Requirement, RequirementPlan, ResearchTask, make_id

# Active query scope: municipal notices, history/heritage, national statistics.
# Restaurant price/hours/license fields remain available only to the legacy
# Claim verifier; the research/query interface does not decompose into them.
FIELD_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("statistics_source", ("统计公报", "数据来源", "口径来源", "公报", "统计局", "可支配收入", "居民收入", "统计数据")),
    ("statistics_method", ("统计口径", "口径", "抽样", "样本", "调查方法", "测算", "住户调查", "指标解释")),
    ("statistics_release", ("数据发布", "新闻发布会", "统计公报", "解读", "发布稿")),
    ("scenic_history", ("历史沿革", "历史", "沿革", "建于", "朝代", "遗址", "遗存", "年代", "起源")),
    ("scenic_explanation", ("由来", "典故", "解释", "文化", "讲解", "介绍", "名称")),
    ("heritage_status", ("世界遗产", "申遗", "文物保护单位", "遗产名录", "全国重点", "UNESCO")),
    ("municipal_notice", ("通知", "公告", "政策", "实施", "规定", "新规", "办法", "条例")),
    ("traffic_restriction", ("限行", "限号", "尾号", "通行", "车辆", "机动车")),
    ("ev_license", ("电动自行车", "电动车", "牌照", "上牌", "登记", "新国标", "号牌")),
    ("ev_restriction", ("电动自行车", "电动车", "停放", "充电", "头盔", "违规")),
    ("municipal_effective", ("实施时间", "生效", "有效期", "施行", "截止")),
]

REQUIREMENT_FIELDS = tuple(field for field, _ in FIELD_KEYWORDS) + ("unknown",)

FIELD_TIME_WINDOW = {
    "statistics_source": "y2",
    "statistics_method": "y2",
    "statistics_release": "y2",
    "scenic_history": "y5",
    "scenic_explanation": "y5",
    "heritage_status": "y5",
    "traffic_restriction": "d30",
    "ev_license": "y1",
    "ev_restriction": "y1",
    "municipal_notice": "m6",
    "municipal_effective": "m6",
}

FIELD_SOURCE_PREFERENCE = {
    "statistics_source": "gov",
    "statistics_method": "gov",
    "statistics_release": "gov",
    "scenic_history": "gov",
    "scenic_explanation": "acad",
    "heritage_status": "gov",
    "traffic_restriction": "gov",
    "ev_license": "gov",
    "ev_restriction": "gov",
    "municipal_notice": "gov",
    "municipal_effective": "gov",
}

FIELD_TERMS = {
    "statistics_source": ("统计公报",),
    "statistics_method": ("统计口径",),
    "statistics_release": ("数据发布",),
    "scenic_history": ("历史沿革",),
    "scenic_explanation": ("由来",),
    "heritage_status": ("世界遗产",),
    "municipal_notice": ("通知",),
    "traffic_restriction": ("限行",),
    "ev_license": ("电动自行车", "上牌"),
    "ev_restriction": ("电动自行车", "通行"),
    "municipal_effective": ("实施时间",),
}

SYSTEM_PROMPT = """你是“需求拆分”器，不是答题器。
把一个研究问题拆成 1–3 个可被搜索验证的需求单元。只输出 JSON，不解释。
只服务三类可靠信源领域：国家统计、历史/文化遗产、市政通知。

输出格式：
{"domain":"领域","requirements":[
  {"text":"可检索的需求句","field":"字段名","subject":"主体，可空","city":"城市，可空",
   "time_window":"d30|m3|m6|y1|y2|y5","source_preference":"gov|news|acad",
   "search_terms":["2024","居民人均可支配收入","41314"],
   "rationale":"为什么拆这一条"}
]}

字段名只能从以下选择：
{fields}

规则：
- 每条需求必须能直接生成搜索查询，不要写“综合分析”“给出结论”这类不可检索的话。
- search_terms 填 2–5 个具体检索词：年份、指标/文件/遗址名、数值、发布主体；不要填整句。
- 历史问题优先拆 scenic_history；世界遗产/文保身份拆 heritage_status。
- 市政问题优先拆 municipal_notice；车辆限行拆 traffic_restriction；电动自行车上牌拆 ev_license；通行/停放/充电拆 ev_restriction；生效时间拆 municipal_effective。
- 统计问题优先拆 statistics_source、statistics_method；需要发布稿/解读时拆 statistics_release。
- 最多 3 条；问题很短时只拆 1 条。
"""


def _infer_fields(text: str) -> list[str]:
    found: list[str] = []
    for field, keywords in FIELD_KEYWORDS:
        if field in found:
            continue
        if any(keyword in text for keyword in keywords):
            found.append(field)
    # A numeric statistic with a derived/period claim needs both source and
    # method, even when the user did not literally say “统计口径”.
    if "statistics_source" in found and any(
        keyword in text for keyword in ("人均", "每月", "折算", "口径", "年")
    ):
        if "statistics_method" not in found:
            found.append("statistics_method")
    return found[:3]


def _extract_terms(
    text: str,
    field: str,
    subject: str | None = None,
    city: str | None = None,
) -> list[str]:
    terms: list[str] = []

    def add(value: str) -> None:
        value = value.strip()
        if value and value not in terms:
            terms.append(value)

    for value in re.findall(r"(?<!\d)(20\d{2})(?!\d)", text):
        add(value)
    for value in re.findall(r"\d+(?:\.\d+)?", text):
        if len(value) >= 2:
            add(value)
    for value in re.findall(r"[“\"]([^”\"]{2,20})[”\"]", text):
        add(value)
    for value in FIELD_TERMS.get(field, ()):
        add(value)
    return terms[:6]


def _build_requirement(
    task: ResearchTask,
    field: str,
    text: str,
    index: int,
    *,
    rationale: str = "",
    search_terms: list[str] | None = None,
) -> Requirement:
    subject = (task.subject or "").strip() or None
    city = (task.city or "").strip() or None
    return Requirement(
        requirement_id=make_id("req", task.task_id, field, index, text[:60]),
        text=text.strip(),
        field=field if field in REQUIREMENT_FIELDS else "unknown",
        subject=subject,
        city=city,
        time_window=FIELD_TIME_WINDOW.get(field, "12m"),
        source_preference=FIELD_SOURCE_PREFERENCE.get(field),
        rationale=rationale,
        importance=index,
        search_terms=search_terms or _extract_terms(text, field, subject, city),
    )


def heuristic_decompose(task: ResearchTask) -> RequirementPlan:
    text = (task.text or "").strip()
    if not text:
        return RequirementPlan(requirements=[], domain=_domain(task), method="heuristic")
    fields = _infer_fields(text)
    if not fields:
        fields = ["unknown"]
    requirements = [
        _build_requirement(
            task,
            field,
            text,
            index + 1,
            rationale=f"关键词映射到 {field}；直接交给查询构造",
        )
        for index, field in enumerate(fields)
    ]
    return RequirementPlan(
        requirements=requirements[:3],
        domain=_domain(task),
        method="heuristic",
        notes=[f"keyword fields: {', '.join(fields[:3])}"],
    )


def _domain(task: ResearchTask) -> str:
    return str((task.constraints or {}).get("domain") or "")


def _normalize_llm_plan(task: ResearchTask, data: dict[str, Any]) -> RequirementPlan | None:
    raw_items = data.get("requirements")
    if not isinstance(raw_items, list):
        return None
    requirements: list[Requirement] = []
    for index, raw in enumerate(raw_items[:3]):
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "").strip()
        if not text:
            continue
        field = str(raw.get("field") or "unknown")
        if field not in REQUIREMENT_FIELDS:
            field = "unknown"
        requirement = _build_requirement(
            task,
            field,
            text,
            index + 1,
            rationale=str(raw.get("rationale") or ""),
            search_terms=[
                str(item).strip()
                for item in (raw.get("search_terms") or [])
                if str(item).strip()
            ],
        )
        city = str(raw.get("city") or "").strip()
        subject = str(raw.get("subject") or "").strip()
        if city:
            requirement.city = city
        if subject:
            requirement.subject = subject
        if raw.get("time_window"):
            requirement.time_window = str(raw["time_window"])
        if raw.get("source_preference"):
            requirement.source_preference = str(raw["source_preference"])
        requirements.append(requirement)
    if not requirements:
        return None
    return RequirementPlan(
        requirements=requirements,
        domain=str(data.get("domain") or _domain(task)),
        method="llm",
        notes=["llm requirement decomposition"],
    )


async def decompose_requirements(llm: Any, task: ResearchTask) -> RequirementPlan:
    """LLM decomposition with deterministic heuristic fallback.

    ``llm`` may be a FakeLLM (returns no plan) or a real client. Any malformed
    response falls back to keyword decomposition so the query interface never
    becomes unusable because of a model hiccup.
    """
    if llm is None:
        return heuristic_decompose(task)
    prompt = SYSTEM_PROMPT.replace("{fields}", "、".join(REQUIREMENT_FIELDS))
    try:
        data = await llm.json(
            "decompose_requirements",
            {
                "question": task.text,
                "domain": _domain(task),
                "subject": task.subject or "",
                "city": task.city or "",
                "expected_fields": list(REQUIREMENT_FIELDS),
            },
            prompt,
        )
    except Exception:
        return heuristic_decompose(task)
    normalized = _normalize_llm_plan(task, data or {})
    return normalized or heuristic_decompose(task)
