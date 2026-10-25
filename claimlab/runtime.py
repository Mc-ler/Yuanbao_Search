"""Build the live or offline runtime once per process."""

from __future__ import annotations

from typing import Any

from .config import Settings
from .evidence import EvidenceImageStore, ScreenshotCapturer
from .llm.client import build_llm
from .pipeline import Pipeline
from .planning import PlanStore
from .search.api import ApiSearchProvider
from .search.archive import ArchiveWriter
from .search.budget import Budget
from .search.cache import DiskCache
from .search.fake import FakeSearchProvider
from .search.gateway import SearchGateway, search_zero_status
from .store.db import Store
from .store.fixtures import fixture_pages, load_all_fixtures


class Sandbox:
    def __init__(self, settings: Settings, providers: dict, fixtures: dict, llm: Any) -> None:
        self.settings = settings
        self.providers = providers
        self.fixtures = fixtures
        self.llm = llm
        self.archive = ArchiveWriter(settings.archive_dir)
        self.cache = DiskCache(settings.cache_dir, "search", settings.cache_ttl_hours * 3600)
        self.store = Store(settings.state_dir / "platform.db")
        self.plan_store = PlanStore()
        self.evidence_images = EvidenceImageStore()
        self.screenshots = ScreenshotCapturer(settings)

    def new_budget(self, profile: str = "verify") -> Budget:
        if profile == "research":
            return Budget(
                self.settings.state_dir,
                max_per_assertion=self.settings.research_max_calls_per_requirement,
                max_per_run=self.settings.research_max_calls_per_run,
                max_per_day=self.settings.max_calls_per_day,
                wall_seconds=self.settings.research_wall_seconds,
            )
        return Budget(
            self.settings.state_dir,
            max_per_assertion=self.settings.max_calls_per_assertion,
            max_per_run=self.settings.max_calls_per_run,
            max_per_day=self.settings.max_calls_per_day,
            wall_seconds=self.settings.run_wall_seconds,
        )

    def new_gateway(self, budget: Budget | None = None) -> SearchGateway:
        return SearchGateway(
            self.settings,
            self.providers,
            budget or self.new_budget(),
            self.archive,
            self.cache,
        )

    def new_pipeline(self, on_event=None) -> Pipeline:
        gateway = self.new_gateway()
        return Pipeline(self.settings, gateway, self.llm, self.archive, gateway.budget, on_event)

    async def health(self) -> dict:
        provider_health = []
        for provider in self.providers.values():
            try:
                provider_health.append((await provider.health()).to_dict())
            except Exception as exc:
                provider_health.append({"provider": getattr(provider, "name", "?"), "error": str(exc)})
        return {
            "settings": self.settings.public_dict(),
            "providers": provider_health,
            "llm": self.llm.describe() if hasattr(self.llm, "describe") else {
                "type": type(self.llm).__name__,
                "model": self.settings.llm_model or None,
                "key_present": self.settings.llm_key_present,
            },
            "cache": self.cache.stats(),
            "search": search_zero_status(),
            "store": self.store.stats(),
            "screenshots": {
                "enabled": self.screenshots.enabled,
                "reason": self.screenshots.reason,
                "chrome": bool(self.screenshots.chrome),
                "last_error": getattr(self.screenshots, "last_error", ""),
            },
            "plans": len(getattr(self.plan_store, "_items", {})),
        }

    async def close(self) -> None:
        for provider in self.providers.values():
            try:
                await provider.close()
            except Exception:
                pass
        try:
            await self.llm.close()
        except Exception:
            pass


def build_sandbox(settings: Settings, force_fake: bool = False) -> Sandbox:
    fixtures = load_all_fixtures(settings.fixtures_dir)
    use_fake = force_fake or settings.search_provider == "fake" or not settings.search_api_key
    if use_fake:
        settings.search_provider = "fake"
        # A fake provider is already deterministic; offline would only block it.
        settings.offline = False
        providers = {"fake": FakeSearchProvider(fixture_pages(fixtures))}
    else:
        providers = {"api": ApiSearchProvider(settings)}
    llm = build_llm(settings)
    return Sandbox(settings, providers, fixtures, llm)
