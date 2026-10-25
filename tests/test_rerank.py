"""Rerank parser: IDs only, clamp scores, fall back on errors."""

import asyncio

from claimlab.contracts import Requirement, SearchPage
from claimlab.skills.dedup import page_key
from claimlab.skills.rerank import rerank_pages


def pages() -> list[SearchPage]:
    return [
        SearchPage(title="西安城墙历史沿革", url="https://www.xa.gov.cn/a", domain="www.xa.gov.cn", date="2025-01-01", passage="西安城墙历史沿革"),
        SearchPage(title="南京城墙申遗", url="https://www.nanjing.gov.cn/b", domain="www.nanjing.gov.cn", date="2024-01-01", passage="南京城墙申遗"),
    ]


def requirement() -> Requirement:
    return Requirement(
        requirement_id="r1",
        text="西安城墙历史沿革",
        field="scenic_history",
        focus="西安城墙",
        search_terms=["西安城墙", "历史沿革"],
    )


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload

    async def json(self, task, payload, system_prompt="", model=None, images=None):
        return self.payload


def test_rerank_keeps_only_known_ids_and_clamps():
    result = asyncio.run(
        rerank_pages(
            FakeLLM({"ranking": [{"id": "p1", "relevance": 1.7}, {"id": "bad", "relevance": 0.9}]}),
            "问题",
            requirement(),
            pages(),
        )
    )
    assert result[page_key(pages()[0])] == 1.0
    assert page_key(pages()[1]) not in result


def test_rerank_failure_returns_empty_for_deterministic_fallback():
    class BrokenLLM:
        async def json(self, *args, **kwargs):
            raise RuntimeError("boom")

    result = asyncio.run(rerank_pages(BrokenLLM(), "问题", requirement(), pages()))
    assert result == {}
