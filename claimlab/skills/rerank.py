"""LLM relevance reranking for research sources.

The deterministic pipeline is good at "is this an official domain" and weak at
"is this page about the requirement". This skill asks the model to score the
top candidates for one requirement, then the ledger uses that order before the
A/B grade. It never invents URLs: only IDs supplied in the prompt are accepted.
"""

from __future__ import annotations

import logging
from typing import Any

from ..contracts import Requirement, SearchPage
from ..logging import event
from .content import best_excerpt
from .dedup import page_key
from .grading import grade_page
from .source_policy import is_relevant

logger = logging.getLogger("claimlab.rerank")

SYSTEM_PROMPT = """你是来源重排器，不是答题器。给定一个研究问题、一个需求，以及候选网页的标题/摘要，判断每页对满足该需求的相关性。只输出 JSON。
输出格式：{"ranking":[{"id":"p1","relevance":0.92,"reason":"包含2024年官方统计公报原文"}]}
规则：
1. 只能使用给定的 id，禁止编造 id 或 URL。
2. relevance 取 0–1：1=直接给出需求所需的事实/原文/数据；0.5=相关但只覆盖一部分；0=无关、旅游攻略、其他城市、泛泛介绍。
3. 优先官方原始文件、统计公报、政策原文、权威媒体的直接报道；百科/自媒体/聚合页降权。
4. 问题中的限定条件（年份、数值、地点、主体）缺失时不能给高分。
5. 对每条候选都给出评分；不要解释评分体系。
"""

_GRADE_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4}


def _deterministic_rank(page: SearchPage) -> tuple:
    grade = grade_page(page).grade
    return (
        _GRADE_ORDER.get(grade, 9),
        -float(page.score or 0.0),
        page.date or "",
        page.url,
    )


def _candidate_pool(
    pages: list[SearchPage],
    requirement: Requirement,
    top_n: int,
) -> list[SearchPage]:
    relevant = [page for page in pages if is_relevant(page, requirement)]
    pool = relevant or pages
    ordered = sorted(pool, key=_deterministic_rank)
    return ordered[: max(1, top_n)]


async def rerank_pages(
    llm: Any,
    question: str,
    requirement: Requirement,
    pages: list[SearchPage],
    *,
    top_n: int = 30,
) -> dict[str, float]:
    """Return {page_key: relevance 0..1}; empty dict means "use deterministic"."""
    if llm is None or not pages:
        return {}
    pool = _candidate_pool(pages, requirement, top_n)
    if not pool:
        return {}
    id_to_key = {f"p{index}": page_key(page) for index, page in enumerate(pool, start=1)}
    payload = {
        "question": question,
        "requirement": {
            "text": requirement.text,
            "field": requirement.field,
            "focus": requirement.focus,
            "search_terms": requirement.search_terms,
            "time_window": requirement.time_window,
        },
        "pages": [
            {
                "id": f"p{index}",
                "title": page.title,
                "domain": page.domain,
                "date": page.date or "",
                "score": page.score,
                "snippet": best_excerpt(page, requirement.search_terms, max_chars=320),
            }
            for index, page in enumerate(pool, start=1)
        ],
    }
    try:
        data = await llm.json("rerank_pages", payload, SYSTEM_PROMPT)
    except Exception as exc:
        event(
            logger,
            "rerank.fallback",
            level=logging.WARNING,
            field=requirement.field,
            reason=f"{type(exc).__name__}: {str(exc)[:200]}",
        )
        return {}
    ranking = data.get("ranking") if isinstance(data, dict) else None
    if not isinstance(ranking, list):
        event(
            logger,
            "rerank.fallback",
            level=logging.WARNING,
            field=requirement.field,
            reason="invalid ranking JSON",
        )
        return {}
    scores: dict[str, float] = {}
    for item in ranking:
        if not isinstance(item, dict):
            continue
        page_id = str(item.get("id") or "")
        key = id_to_key.get(page_id)
        if key is None:
            continue
        try:
            value = float(item.get("relevance"))
        except (TypeError, ValueError):
            continue
        scores[key] = max(0.0, min(1.0, value))
    event(
        logger,
        "rerank.done",
        field=requirement.field,
        candidates=len(pool),
        scored=len(scores),
    )
    return scores
