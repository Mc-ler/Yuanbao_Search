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

# Ordered so more specific domains win before generic "notice"/"history".
FIELD_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("statistics_source", ("统计公报", "数据来源", "口径来源", "公报", "统计局", "可支配收入", "居民收入", "统计数据")),
    ("statistics_method", ("统计口径", "口径", "抽样", "样本", "调查方法", "测算")),
    ("scenic_history", ("历史沿革", "历史", "沿革", "建于", "朝代", "遗址", "年代", "起源")),
    ("scenic_explanation", ("由来", "典故", "解释", "文化", "讲解", "介绍")),
    ("traffic_restriction", ("限行", "限号", "尾号", "通行", "车辆")),
    ("ev_license", ("电动自行车", "电动车", "牌照", "上牌", "登记", "新国标")),
    ("municipal_notice", ("通知", "公告", "政策", "实施", "规定")),
    ("business_status", ("营业", "闭店", "停业", "开业", "注销")),
    ("price", ("人均", "价格", "多少钱", "消费")),
    ("hours", ("营业时间", "周一", "营业日")),
    ("address", ("地址", "位于")),
    ("reservation", ("预约", "限流", "门票")),
    ("license", ("许可", "资质", "营业执照", "备案")),
    ("penalty", ("处罚", "罚款", "抽检", "不合格")),
    ("ad_disclosure", ("广告", "探店", "推广", "商业合作")),
]

REQUIREMENT_FIELDS = tuple(field for field, _ in FIELD_KEYWORDS) + ("unknown",)

FIELD_TIME_WINDOW = {
    "statistics_source": "y2",
    "statistics_method": "y2",
    "scenic_history": "y5",
    "scenic_explanation": "y5",
    "traffic_restriction": "d30",
    "ev_license": "y1",
    "municipal_notice": "m6",
}

FIELD_SOURCE_PREFERENCE = {
    "statistics_source": "gov",
    "statistics_method": "gov",
    "scenic_history": "gov",
    "scenic_explanation": "acad",
    "traffic_restriction": "gov",
    "ev_license": "gov",
    "municipal_notice": "gov",
}

SYSTEM_PROMPT = """你是“需求拆分”器，不是答题器。
把一个研究问题拆成 1–3 个可被搜索验证的需求单元。只输出 JSON，不解释。

输出格式：
{"domain":"领域","requirements":[
  {"text":"可检索的需求句","field":"字段名","subject":"主体，可空","city":"城市，可空",
   "time_window":"d30|m3|m6|y1|y2|y5","source_preference":"gov|news|acad|finance",
   "rationale":"为什么拆这一条"}
]}

字段名只能从以下选择：
{fields}

规则：
- 每条需求必须能直接生成搜索查询，不要写“综合分析”“给出结论”这类不可检索的话。
- 不回答问题本身，不预设结论，不评价个人。
- 最多 3 条；问题很短时只拆 1 条。
"""


def _infer_fields(text: str) -> list[str]:
    found: list[str] = []
    for field, keywords in FIELD_KEYWORDS:
        if field in found:
            continue
        if any(keyword in text for keyword in keywords):
            found.append(field)
    if any(field in found for field in ("statistics_source", "statistics_method")):
        found = [field for field in found if field != "price"]
    return found[:3]


def _build_requirement(
    task: ResearchTask,
    field: str,
    text: str,
    index: int,
    *,
    rationale: str = "",
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
