"""Search provider contract shared by API, MCP and fake providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..contracts import SearchBatch, SearchRequest


@dataclass
class ProviderHealth:
    provider: str
    configured: bool
    available: bool
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "configured": self.configured,
            "available": self.available,
            "detail": self.detail,
        }


class SearchProvider(Protocol):
    name: str

    async def search(self, request: SearchRequest) -> SearchBatch: ...

    async def health(self) -> ProviderHealth: ...

    async def close(self) -> None: ...
