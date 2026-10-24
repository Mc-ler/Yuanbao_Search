import asyncio
from pathlib import Path

from claimlab.llm.client import FakeLLM
from claimlab.planning import PlanStore, build_research_plan


def test_planner_builds_three_queries_with_focus():
    plan = asyncio.run(build_research_plan(FakeLLM(), "西安城墙现存主体是什么年代修建的？"))
    assert plan.items
    item = plan.items[0]
    assert 1 <= len(item.queries) <= 3
    assert item.requirement.focus
    joined = " ".join(q.query for q in item.queries)
    assert item.requirement.focus in joined or "西安城墙" in joined
    assert plan.plan_id == asyncio.run(build_research_plan(FakeLLM(), "西安城墙现存主体是什么年代修建的？")).plan_id


def test_plan_store_roundtrip_and_expiry():
    plan = asyncio.run(build_research_plan(FakeLLM(), "测试问题"))
    store = PlanStore(ttl_seconds=60)
    store.put(plan)
    assert store.get(plan.plan_id) is plan
    expired = PlanStore(ttl_seconds=-1)
    expired.put(plan)
    assert expired.get(plan.plan_id) is None
