"""Site policy: exact host only, no apex, no site: operator."""

from claimlab.contracts import Requirement
from claimlab.skills.query import coerce_llm_queries, normalize_site, strip_site_operator


def requirement() -> Requirement:
    return Requirement(requirement_id="r1", text="西安城墙历史沿革", field="scenic_history")


def test_site_requires_exact_indexed_host():
    assert normalize_site("www.xa.gov.cn") == "www.xa.gov.cn"
    assert normalize_site("https://www.stats.gov.cn/path") == "www.stats.gov.cn"
    assert normalize_site("dianping.com") == "dianping.com"
    assert normalize_site("xa.gov.cn") is None
    assert normalize_site("gov.cn") is None
    assert normalize_site("stats.gov.cn") is None
    assert normalize_site("") is None


def test_site_operator_is_removed():
    assert strip_site_operator("site:stats.gov.cn 西安城墙 历史沿革") == "西安城墙 历史沿革"
    assert strip_site_operator("西安城墙 历史沿革") == "西安城墙 历史沿革"


def test_llm_queries_drop_apex_site_and_operator():
    data = {
        "queries": [
            {"query": "site:stats.gov.cn 2024年居民收入", "site": "stats.gov.cn"},
            {"query": "西安城墙 历史沿革", "site": "www.xa.gov.cn", "industry": "gov"},
        ]
    }
    plans = coerce_llm_queries(data, requirement())
    assert len(plans) == 2
    assert plans[0].query == "2024年居民收入"
    assert plans[0].site is None
    assert plans[1].site == "www.xa.gov.cn"
    assert plans[1].industry == "gov"
