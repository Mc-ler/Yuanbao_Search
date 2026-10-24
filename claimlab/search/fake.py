"""Deterministic fake provider used for offline tests.

Each fixture carries `mock_pages`; every page may have `_triggers` used to
match a query. No network, no key, no hidden randomness.
"""

from __future__ import annotations

import time
from typing import Any

from ..contracts import SearchBatch, SearchRequest
from .base import ProviderHealth
from .normalize import normalize_page


class FakeSearchProvider:
    name = "fake"

    def __init__(self, pages: list[dict[str, Any]] | None = None, scenario: str = "") -> None:
        self.pages = pages or []
        self.scenario = scenario
        self.calls = 0

    @classmethod
    def from_fixture(cls, fixture: dict[str, Any]) -> "FakeSearchProvider":
        pages = fixture.get("mock_pages") or []
        return cls(pages=pages, scenario=str(fixture.get("fixture_id") or ""))

    def _match(self, query: str) -> list[dict[str, Any]]:
        lowered = query.lower()
        matched: list[dict[str, Any]] = []
        for item in self.pages:
            triggers = item.get("_triggers") or []
            if not triggers:
                continue
            if any(str(trigger).lower() in lowered for trigger in triggers):
                matched.append(item)
        return matched

    async def search(self, request: SearchRequest) -> SearchBatch:
        started = time.perf_counter()
        self.calls += 1
        matched = self._match(request.query)
        pages = []
        for item in matched:
            raw = {k: v for k, v in item.items() if not k.startswith("_")}
            pages.append(normalize_page(raw))
        return SearchBatch(
            provider=self.name,
            request_id=f"fake-{self.calls}",
            version="standard-mock",
            pages=pages,
            raw={"mock": True, "scenario": self.scenario, "matched": len(pages)},
            latency_ms=(time.perf_counter() - started) * 1000 + 5,
            warnings=["mock provider: not a real search"],
            query=request.query,
            request=request,
        )

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider=self.name,
            configured=True,
            available=True,
            detail="offline fixture provider; results are clearly marked mock",
        )

    async def close(self) -> None:
        return None
