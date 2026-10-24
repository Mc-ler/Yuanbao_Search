"""Single search entry point for the API and offline fake provider.

The gateway owns caching, budget charging, request logging, and the
append-only audit record. It always returns a normalized SearchBatch.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict
from typing import Any

from ..config import Settings
from ..contracts import SearchBatch, SearchPage, SearchRequest
from ..logging import event
from .archive import ArchiveWriter
from .base import ProviderHealth, SearchProvider
from .budget import Budget, BudgetExceeded
from .cache import DiskCache, cache_key

logger = logging.getLogger("claimlab.search")


def _official(domain: str) -> bool:
    return domain.endswith(".gov.cn") or domain in {"gov.cn", "stats.gov.cn"}


def _batch_fields(batch: SearchBatch) -> dict[str, Any]:
    domains = [page.domain for page in batch.pages if page.domain]
    return {
        "provider": batch.provider,
        "pages": len(batch.pages),
        "official": sum(1 for domain in domains if _official(domain)),
        "domains": domains[:8],
        "latency_ms": round(batch.latency_ms, 1),
        "error_kind": batch.error_kind or None,
        "error": batch.error,
    }



def _batch_to_cache(batch: SearchBatch) -> dict[str, Any]:
    return {
        "provider": batch.provider,
        "request_id": batch.request_id,
        "version": batch.version,
        "pages": [asdict(page) for page in batch.pages],
        "raw": batch.raw,
        "latency_ms": batch.latency_ms,
        "warnings": batch.warnings,
        "error": batch.error,
        "error_kind": batch.error_kind,
        "query": batch.query,
    }


def _batch_from_cache(data: dict[str, Any], request: SearchRequest) -> SearchBatch:
    pages: list[SearchPage] = []
    for item in data.get("pages", []):
        if not isinstance(item, dict):
            continue
        fields = {key: item.get(key) for key in SearchPage.__dataclass_fields__ if key in item}
        pages.append(SearchPage(**fields))
    return SearchBatch(
        provider=str(data.get("provider") or "cache"),
        request_id=str(data.get("request_id") or ""),
        version=str(data.get("version") or ""),
        pages=pages,
        raw=data.get("raw"),
        latency_ms=float(data.get("latency_ms") or 0.0),
        warnings=list(data.get("warnings") or []),
        error=data.get("error"),
        error_kind=str(data.get("error_kind") or ""),
        cache_hit=True,
        query=request.query,
        request=request,
    )


class SearchGateway:
    def __init__(
        self,
        settings: Settings,
        providers: dict[str, SearchProvider],
        budget: Budget,
        archive: ArchiveWriter,
        cache: DiskCache | None = None,
    ) -> None:
        self.settings = settings
        self.providers = providers
        self.budget = budget
        self.archive = archive
        self.cache = cache or DiskCache(
            settings.cache_dir,
            "search",
            settings.cache_ttl_hours * 3600,
        )
        self.calls = 0
        self.cache_hits = 0
        self.calls_by_provider: dict[str, int] = {}

    def _candidates(self) -> list[str]:
        mode = self.settings.search_provider
        return ["api"] if mode == "api" and "api" in self.providers else (["fake"] if mode == "fake" and "fake" in self.providers else [])

    async def search(
        self,
        run_id: str,
        assertion_id: str,
        plan: Any,
        *,
        use_cache: bool = True,
    ) -> SearchBatch:
        request = plan.to_request()
        event(
            logger,
            "search.start",
            run_id=run_id,
            assertion_id=assertion_id,
            query=request.query,
            site=request.site,
            industry=request.industry,
            freshness=request.freshness,
            provider=self.settings.search_provider,
            use_cache=use_cache,
        )
        key = cache_key("search", self.settings.search_provider, request.to_api_body())
        cached = self.cache.get(key) if use_cache else None
        if cached is not None:
            batch = _batch_from_cache(cached, request)
            self.budget.hit()
            self.cache_hits += 1
            self.archive.write_search(run_id, request.to_api_body(), batch, batch.provider, True)
            event(logger, "search.cache_hit", query=request.query, **_batch_fields(batch))
            return batch

        if self.settings.offline:
            batch = SearchBatch(
                provider=self.settings.search_provider,
                error="cache miss in offline mode (run a live search or warm the cache first)",
                error_kind="cache",
                request=request,
                query=request.query,
            )
            event(logger, "search.error", level=logging.WARNING, query=request.query, **_batch_fields(batch))
            return batch

        try:
            self.budget.charge(assertion_id)
        except BudgetExceeded as exc:
            batch = SearchBatch(
                provider=self.settings.search_provider,
                error=f"budget: {exc.reason}",
                error_kind="budget",
                request=request,
                query=request.query,
            )
            event(logger, "search.error", level=logging.WARNING, query=request.query, **_batch_fields(batch))
            return batch

        candidates = self._candidates()
        if not candidates:
            batch = SearchBatch(
                provider=self.settings.search_provider,
                error=f"provider not configured: {self.settings.search_provider}",
                error_kind="config",
                request=request,
                query=request.query,
            )
            event(logger, "search.error", level=logging.WARNING, query=request.query, **_batch_fields(batch))
            return batch

        last: SearchBatch | None = None
        for name in candidates:
            provider = self.providers[name]
            batch = await provider.search(request)
            self.calls += 1
            self.calls_by_provider[name] = self.calls_by_provider.get(name, 0) + 1
            if batch.ok:
                provider_key = cache_key("search", name, request.to_api_body())
                if batch.pages:
                    self.cache.set(provider_key, _batch_to_cache(batch))
                self.archive.write_search(run_id, request.to_api_body(), batch, name, False)
                event(
                    logger,
                    "search.done" if batch.pages else "search.zero",
                    level=logging.INFO if batch.pages else logging.WARNING,
                    query=request.query,
                    **_batch_fields(batch),
                )
                return batch
            last = batch
            break
        assert last is not None
        self.archive.write_search(run_id, request.to_api_body(), last, last.provider, False)
        event(logger, "search.error", level=logging.WARNING, query=request.query, **_batch_fields(last))
        return last

    async def health(self) -> list[ProviderHealth]:
        result = []
        for name, provider in self.providers.items():
            try:
                result.append(await provider.health())
            except Exception as exc:
                result.append(ProviderHealth(name, configured=False, available=False, detail=str(exc)))
        return result

    def stats(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "cache_hits": self.cache_hits,
            "calls_by_provider": dict(self.calls_by_provider),
            "budget": self.budget.summary(),
            "cache": self.cache.stats(),
        }

    async def close(self) -> None:
        for provider in self.providers.values():
            try:
                await provider.close()
            except Exception:
                pass
