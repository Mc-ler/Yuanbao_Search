"""REST provider for Tencent Yuanbao Search (Bearer service API KEY)."""

from __future__ import annotations

import time

import httpx

from ..config import Settings
from ..contracts import SearchBatch, SearchRequest
from ..keys import bearer_auth_header
from .base import ProviderHealth
from .normalize import normalize_api_response


def classify_status(status: int) -> str:
    if status in (401, 403):
        return "auth"
    if status == 429:
        return "rate_limit"
    if status >= 500:
        return "server"
    if status >= 400:
        return "client"
    return "unknown"


class ApiSearchProvider:
    name = "api"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._url = f"{settings.search_base_url}/SearchPro"
        headers = {"Content-Type": "application/json; charset=UTF-8"}
        auth = bearer_auth_header(settings.search_api_key)
        if auth:
            headers["Authorization"] = auth
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(20.0, connect=8.0),
            headers=headers,
        )

    async def search(self, request: SearchRequest) -> SearchBatch:
        started = time.perf_counter()
        try:
            response = await self._client.post(self._url, json=request.to_api_body())
        except httpx.HTTPError as exc:
            return SearchBatch(
                provider=self.name,
                latency_ms=(time.perf_counter() - started) * 1000,
                error=f"transport: {type(exc).__name__}",
                error_kind="transport",
                request=request,
                query=request.query,
            )
        latency = (time.perf_counter() - started) * 1000
        if response.status_code != 200:
            return SearchBatch(
                provider=self.name,
                latency_ms=latency,
                error=f"HTTP {response.status_code}: {response.text[:300]}",
                error_kind=classify_status(response.status_code),
                raw={"status": response.status_code, "text": response.text[:2000]},
                request=request,
                query=request.query,
            )
        try:
            payload = response.json()
        except ValueError:
            return SearchBatch(
                provider=self.name,
                latency_ms=latency,
                error="response is not JSON",
                error_kind="server",
                raw={"text": response.text[:2000]},
                request=request,
                query=request.query,
            )
        return normalize_api_response(payload, self.name, latency, request)

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider=self.name,
            configured=bool(self.settings.search_api_key),
            available=bool(self.settings.search_api_key),
            detail="Bearer /SearchPro; configuration-only health (no live call)",
            endpoint="/SearchPro",
            transport="https",
        )

    async def close(self) -> None:
        await self._client.aclose()
