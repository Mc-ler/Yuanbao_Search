"""Shared research planner used by /api/plan and /api/research.

One planner produces the exact query set a research run will execute, so the
preview and the run cannot drift apart (the old /api/plan used templates while
/api/research used the LLM). Plans are kept in memory for a short TTL and can be
executed by plan_id.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .contracts import QueryPlan, Requirement, ResearchTask, make_id
from .skills.query import (
    build_queries_llm,
    plan_fallback_queries,
    plan_key,
    plan_requery_queries,
    plan_requirement_queries,
)
from .skills.requirements import decompose_requirements

PROMPT_VERSION = "v3.1"
MAX_INITIAL_PER_REQUIREMENT = 5


@dataclass
class PlanItem:
    requirement: Requirement
    queries: list[QueryPlan] = field(default_factory=list)
    fallbacks: list[QueryPlan] = field(default_factory=list)
    requeries: list[QueryPlan] = field(default_factory=list)


@dataclass
class ResearchPlan:
    plan_id: str
    text: str
    domain: str
    method: str
    items: list[PlanItem]
    created_at: float
    prompt_version: str = PROMPT_VERSION

    def all_queries(self) -> list[QueryPlan]:
        return [plan for item in self.items for plan in item.queries]

    def all_fallbacks(self) -> list[QueryPlan]:
        return [plan for item in self.items for plan in item.fallbacks]

    def all_requeries(self) -> list[QueryPlan]:
        return [plan for item in self.items for plan in item.requeries]

    def as_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "domain": self.domain,
            "method": self.method,
            "requirements": [item.requirement for item in self.items],
            "queries": self.all_queries(),
            "fallback_queries": self.all_fallbacks(),
            "requery_queries": self.all_requeries(),
        }


async def build_research_plan(
    llm: Any,
    text: str,
    *,
    max_initial: int = MAX_INITIAL_PER_REQUIREMENT,
    results_per_query: int = 20,
) -> ResearchPlan:
    """Build requirements and the exact initial queries for a question."""
    task = ResearchTask(text=text, mode="research_topic")
    decomposition = await decompose_requirements(llm, task)
    items: list[PlanItem] = []
    used: set[tuple[str, str | None, str | None]] = set()
    cap = max(1, int(max_initial))
    for requirement in decomposition.requirements:
        llm_queries = [
            plan
            for plan in await build_queries_llm(llm, requirement)
            if plan_key(plan) not in used
        ]
        template_queries = plan_requirement_queries(
            requirement,
            used=used,
            max_plans=max(cap, 5),
        )
        merged: list[QueryPlan] = []
        seen: set[tuple[str, str | None, str | None]] = set()
        for plan in [*llm_queries, *template_queries]:
            key = plan_key(plan)
            if key in seen or key in used:
                continue
            plan.cnt = results_per_query
            merged.append(plan)
            seen.add(key)
            if len(merged) >= cap:
                break
        queries = merged[:cap]
        used.update(plan_key(plan) for plan in queries)
        fallbacks = plan_fallback_queries(requirement, used=used, max_plans=2)
        used.update(plan_key(plan) for plan in fallbacks)
        requeries = plan_requery_queries(requirement, used=used, max_plans=2)
        used.update(plan_key(plan) for plan in requeries)
        for plan in [*fallbacks, *requeries]:
            plan.cnt = results_per_query
        items.append(
            PlanItem(
                requirement=requirement,
                queries=queries,
                fallbacks=fallbacks,
                requeries=requeries,
            )
        )
    query_signature = "|".join(
        f"{item.requirement.field}:{item.requirement.focus}:"
        + ",".join(plan.query for plan in item.queries)
        for item in items
    )
    return ResearchPlan(
        plan_id=make_id(
            "plan",
            text,
            PROMPT_VERSION,
            decomposition.method,
            query_signature,
        ),
        text=text,
        domain=decomposition.domain,
        method=decomposition.method,
        items=items,
        created_at=time.time(),
    )


class PlanStore:
    """Small in-memory plan cache; plans are previews, not persisted."""

    def __init__(self, ttl_seconds: int = 900, max_entries: int = 50) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._items: dict[str, ResearchPlan] = {}

    def put(self, plan: ResearchPlan) -> None:
        self._prune()
        self._items[plan.plan_id] = plan
        while len(self._items) > self.max_entries:
            oldest = min(self._items.values(), key=lambda item: item.created_at)
            self._items.pop(oldest.plan_id, None)

    def get(self, plan_id: str) -> ResearchPlan | None:
        plan = self._items.get(plan_id)
        if plan is None:
            return None
        if time.time() - plan.created_at > self.ttl_seconds:
            self._items.pop(plan_id, None)
            return None
        return plan

    def _prune(self) -> None:
        now = time.time()
        expired = [
            key for key, plan in self._items.items()
            if now - plan.created_at > self.ttl_seconds
        ]
        for key in expired:
            self._items.pop(key, None)
