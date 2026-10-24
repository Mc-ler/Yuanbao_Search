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
    assert answer["verdict"]
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
