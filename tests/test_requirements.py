import json
from pathlib import Path

from claimlab.contracts import ResearchTask, Requirement, SearchPage
from claimlab.skills.grading import grade_page
from claimlab.skills.query import (
    plan_fallback_queries,
    plan_key,
    plan_requery_queries,
    plan_requirement_queries,
)
from claimlab.skills.requirements import heuristic_decompose
from claimlab.skills.source_policy import next_action, source_tier
from scripts.git_push import FORBIDDEN_STAGED, safe_remote

ROOT = Path(__file__).resolve().parent.parent


def _task(text: str, subject: str = "示例市", city: str = "西安") -> ResearchTask:
    return ResearchTask(text=text, mode="research_topic", subject=subject, city=city)


def test_statistics_question_decomposes_source_and_method():
    plan = heuristic_decompose(
        _task("某市2025年统计公报中“居民人均可支配收入”的统计口径和数据来源是什么？")
    )
    fields = {item.field for item in plan.requirements}
    assert "statistics_source" in fields
    assert "statistics_method" in fields
    assert len(plan.requirements) <= 3
    assert plan.method == "heuristic"


def test_income_statistic_keeps_source_method_and_target_terms():
    plan = heuristic_decompose(
        _task("2024年全国居民人均可支配收入达到41314元，这个数据靠谱吗？")
    )
    fields = {item.field for item in plan.requirements}
    assert "statistics_source" in fields
    assert "statistics_method" in fields
    assert "price" not in fields
    source = next(item for item in plan.requirements if item.field == "statistics_source")
    assert "2024" in source.search_terms
    assert "41314" in source.search_terms


def test_heritage_question_gets_heritage_field():
    plan = heuristic_decompose(_task("西安城墙是否列入世界遗产？唐代遗存在哪里？"))
    fields = {item.field for item in plan.requirements}
    assert "heritage_status" in fields
    assert "scenic_history" in fields


def test_scenic_question_decomposes_history_and_explanation():
    plan = heuristic_decompose(_task("某景区（如兵马俑、大雁塔）的历史沿革、建置年代和名称由来是什么？"))
    fields = {item.field for item in plan.requirements}
    assert "scenic_history" in fields
    assert "scenic_explanation" in fields


def test_vehicle_question_decomposes_notice_restriction_and_ev_license():
    plan = heuristic_decompose(
        _task("某市2025年机动车尾号限行通知的规则是什么？电动自行车上牌需要哪些材料？")
    )
    fields = {item.field for item in plan.requirements}
    assert {"traffic_restriction", "ev_license", "municipal_notice"} <= fields
    assert len(plan.requirements) == 3


def test_requirement_queries_are_directed_and_keep_requirement_id():
    requirement = Requirement(
        requirement_id="req-test",
        text="某市统计公报中居民人均可支配收入的来源",
        field="statistics_source",
        subject="某市统计局",
        city="西安",
    )
    plans = plan_requirement_queries(requirement, subject="某市统计局", city="西安")
    assert plans
    assert all(plan.claim_id == "" for plan in plans)
    assert all(plan.requirement_id == "req-test" for plan in plans)
    assert any(plan.industry == "gov" for plan in plans)
    assert any(plan.precision == "precise" for plan in plans)


def test_examples_are_aligned_and_questions_can_be_filled():
    expected = {
        "q1_statistics_bulletin": "statistics_source",
        "q2_scenic_history": "scenic_history",
        "q3_vehicle_restriction": "municipal_notice",
    }
    for example_id, field in expected.items():
        data = json.loads((ROOT / "examples" / f"{example_id}.json").read_text(encoding="utf-8"))
        assert data["example_id"] == example_id
        assert isinstance(data["question"], str)
        assert field in data["query_fields"]
        assert data["question_suggestion"]


def test_fallback_and_requery_are_unique():
    requirement = Requirement(
        requirement_id="req-fallback",
        text="国家统计局2024年居民人均可支配收入统计口径",
        field="statistics_method",
        subject="国家统计局",
        search_terms=["2024", "居民人均可支配收入", "41314"],
    )
    initial = plan_requirement_queries(requirement)
    used = {plan_key(plan) for plan in initial}
    fallback = plan_fallback_queries(requirement, used=used)
    used.update(plan_key(plan) for plan in fallback)
    requery = plan_requery_queries(requirement, used=used)
    assert initial
    assert fallback
    assert requery
    keys = [plan_key(plan) for plan in [*initial, *fallback, *requery]]
    assert len(keys) == len(set(keys))
    assert any("2024" in plan.query and "41314" in plan.query for plan in initial)
    assert fallback[0].strategy == "B/C降级"
    assert requery[0].strategy == "再查询"


def test_source_policy_prefers_ab_then_falls_back():
    assert source_tier([SearchPage(domain="stats.gov.cn")]) == "A/B"
    assert source_tier([SearchPage(domain="example.com")]) == "insufficient"
    assert next_action("A/B", attempts=1) == "accept"
    assert next_action("B/C", attempts=1) == "fallback"
    assert next_action("insufficient", attempts=1) == "requery"
    assert next_action("insufficient", attempts=2) == "insufficient"


def test_history_is_not_age_downgraded_like_a_municipal_notice():
    page = SearchPage(domain="stats.gov.cn", age_days=1000)
    assert grade_page(page).grade == "B"
    assert grade_page(page, field="scenic_history").grade == "A"
    assert grade_page(page, field="statistics_source").grade == "B"


def test_git_push_does_not_commit_env_or_local_config_and_strips_credentials():
    assert FORBIDDEN_STAGED.search(".env")
    assert FORBIDDEN_STAGED.search("config/.env.local")
    assert FORBIDDEN_STAGED.search(".push.json")
    assert FORBIDDEN_STAGED.search("push.config.json")
    assert not FORBIDDEN_STAGED.search(".env.example")
    assert not FORBIDDEN_STAGED.search("push.config.example.json")
    assert safe_remote("https://user:token@github.com/org/repo.git") == "https://github.com/org/repo.git"
