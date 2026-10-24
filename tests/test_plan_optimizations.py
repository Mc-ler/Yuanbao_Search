"""Tests for the plan optimizations: cnt, answer/citation, LLM query coercion, store."""

import asyncio

from claimlab.contracts import Requirement, SearchRequest, normalize_cnt
from claimlab.skills.answer import build_answer, build_citations
from claimlab.skills.query import build_queries_llm, coerce_llm_queries
from claimlab.store.db import Store


def test_cnt_is_string_and_snapped():
    assert normalize_cnt(7) == 10
    assert normalize_cnt(13) == 10
    assert normalize_cnt(50) == 50
    assert normalize_cnt(999) == 50
    assert normalize_cnt("20") == 20
    body = SearchRequest(query="q", cnt=10).to_api_body()
    assert body["Cnt"] == "10"
    assert isinstance(body["Cnt"], str)


def test_build_citations_dedupes_by_url():
    rows = [
        {"field": "f1", "top_sources": [{"url": "https://a/x", "title": "A", "domain": "a", "grade": "A"}]},
        {
            "field": "f2",
            "top_sources": [
                {"url": "https://a/x", "title": "A", "domain": "a", "grade": "A"},
                {"url": "https://b/x", "title": "B", "domain": "b", "grade": "B"},
            ],
        },
    ]
    citations = build_citations(rows)
    assert len(citations) == 2
    assert citations[0]["n"] == 1
    assert citations[1]["n"] == 2


def test_build_answer_rule_fallback():
    rows = [
        {
            "field": "scenic_history",
            "tier": "A/B",
            "top_sources": [{"url": "https://gov.cn/x", "title": "t", "domain": "gov.cn", "grade": "A"}],
        }
    ]
    answer = asyncio.run(build_answer(None, "q", rows))
    assert answer["engine"] == "rule"
    assert answer["text"]
    assert answer["citations"]


def test_coerce_llm_queries_validates_fields():
    req = Requirement(requirement_id="r1", text="t", field="scenic_history")
    data = {
        "queries": [
            {"query": "西安城墙 历史沿革", "site": "gov.cn", "industry": "gov", "freshness": "y5", "mode": 0, "cnt": 20},
            {"query": "bad", "industry": "bogus", "freshness": "bogus", "cnt": 999},
        ]
    }
    plans = coerce_llm_queries(data, req)
    assert len(plans) == 2
    assert plans[0].cnt == 20
    assert plans[0].industry == "gov"
    assert plans[0].site == "gov.cn"
    assert plans[1].industry is None
    assert plans[1].freshness is None


def test_build_queries_llm_offline_returns_empty():
    req = Requirement(requirement_id="r1", text="t", field="scenic_history")
    plans = asyncio.run(build_queries_llm(None, req))
    assert plans == []


def test_store_roundtrip(tmp_path):
    store = Store(tmp_path / "platform.db")
    assert store.available
    assert store.upsert_run("r1", question="q1", metrics={"pages": 5}, result=[{"field": "f"}])
    assert store.upsert_sources("r1", [{"field": "f", "url": "https://a/x", "grade": "A"}])
    stats = store.stats()
    assert stats["available"] is True
    assert stats["runs"] >= 1
    runs = store.query_runs(q="q1")
    assert runs["total"] >= 1
    detail = store.get_run("r1")
    assert detail is not None
    assert detail["sources"]
    exported = store.export_rows(q="q1")
    assert exported

def test_build_and_render_research_report():
    from claimlab.skills.research_report import build_research_report, render_research_markdown

    rows = [{
        "field": "scenic_history", "text": "西安城墙历史沿革", "tier": "A/B",
        "pages": 10, "relevant_pages": 5,
        "top_sources": [{"grade": "A", "title": "城墙", "domain": "gov.cn", "url": "https://gov.cn/x"}],
    }]
    answer = {
        "text": "结论见 [1]", "engine": "rule",
        "citations": [{"n": 1, "grade": "A", "title": "城墙", "domain": "gov.cn", "date": "", "url": "https://gov.cn/x"}],
    }
    metrics = {"fields": 1, "fields_with_ab": 1, "relevant_official_rate": 1.0, "zero_requirements": 0}
    report = build_research_report("q", rows, answer, metrics)
    assert report["title"] == "研究报告"
    assert report["citations"]
    md = render_research_markdown(report)
    assert "# 研究报告" in md
    assert "[1]" in md

def test_focus_is_the_only_query_entity():
    from claimlab.contracts import Requirement
    from claimlab.skills.query import plan_requirement_queries

    req = Requirement(
        requirement_id="r1",
        text="电动自行车新规有哪些重点",
        field="municipal_notice",
        focus="电动自行车新规",
        search_terms=["电动自行车", "新规"],
    )
    plans = plan_requirement_queries(req)
    assert plans
    for p in plans:
        assert "西安" not in p.query
        assert "电动自行车新规" in p.query or "电动自行车" in p.query
