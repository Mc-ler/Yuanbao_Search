"""Site fallback: a zero-page site query retries once without Site."""

import asyncio

from claimlab.contracts import QueryPlan, SearchBatch, SearchPage
from claimlab.search.fallback import search_with_site_fallback


class FakeGateway:
    def __init__(self):
        self.calls = 0
        self.sites = []

    async def search(self, run_id, assertion_id, plan, use_cache=True):
        self.calls += 1
        self.sites.append(plan.site)
        if self.calls == 1:
            return SearchBatch(provider="fake", request=plan.to_request(), query=plan.query, pages=[])
        return SearchBatch(
            provider="fake",
            request=plan.to_request(),
            query=plan.query,
            pages=[SearchPage(title="t", url="https://www.xa.gov.cn/a")],
        )


def test_zero_site_query_retries_without_site():
    plan = QueryPlan(plan_id="q1", claim_id="", query="西安城墙", site="xa.gov.cn")
    gateway = FakeGateway()
    batch = asyncio.run(search_with_site_fallback(gateway, "run", "a1", plan))
    assert len(batch.pages) == 1
    assert gateway.calls == 2
    assert gateway.sites == ["xa.gov.cn", None]


def test_no_retry_when_first_query_has_pages():
    plan = QueryPlan(plan_id="q1", claim_id="", query="西安城墙", site="www.xa.gov.cn")

    class GoodGateway:
        calls = 0

        async def search(self, *args, **kwargs):
            self.calls += 1
            return SearchBatch(provider="fake", pages=[SearchPage(title="t", url="https://www.xa.gov.cn/a")])

    gateway = GoodGateway()
    batch = asyncio.run(search_with_site_fallback(gateway, "run", "a1", plan))
    assert batch.pages
    assert gateway.calls == 1
