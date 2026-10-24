"""MCP provider for Yuanbao Search (JSON-RPC 2.0 over Streamable HTTP).

Preferred path: the official `mcp` Python SDK handles initialize, session
headers, Streamable HTTP and SSE framing. If the SDK is not installed we fall
back to a deliberately small JSON-RPC client that implements the same single
tool call. Both paths normalize into SearchBatch.
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import AsyncExitStack
from typing import Any

import httpx

from ..config import Settings
from ..contracts import SearchBatch, SearchRequest
from ..keys import bearer_auth_header
from .base import ProviderHealth
from .normalize import normalize_mcp_result

try:  # optional dependency
    from mcp import ClientSession  # type: ignore
    from mcp.client import streamable_http as _streamable_http  # type: ignore

    # MCP 1.x exports streamablehttp_client(url, headers=...).
    # MCP 2.x exports streamable_http_client(url, http_client=...).
    _STREAMABLE_V1 = getattr(_streamable_http, "streamablehttp_client", None)
    _STREAMABLE_V2 = getattr(_streamable_http, "streamable_http_client", None)
    MCP_SDK_AVAILABLE = bool(ClientSession and (_STREAMABLE_V1 or _STREAMABLE_V2))
    MCP_SDK_ERROR = "" if MCP_SDK_AVAILABLE else "no streamable HTTP client in mcp SDK"
except Exception as exc:  # pragma: no cover - exercised only when SDK absent
    ClientSession = None  # type: ignore
    _STREAMABLE_V1 = None
    _STREAMABLE_V2 = None
    MCP_SDK_AVAILABLE = False
    MCP_SDK_ERROR = f"{type(exc).__name__}: {exc}"


class McpSearchProvider:
    name = "mcp"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._url = f"{settings.search_base_url}/Mcp"
        self._headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        auth = bearer_auth_header(settings.search_api_key)
        if auth:
            self._headers["Authorization"] = auth
        self._session = None
        self._stack: AsyncExitStack | None = None
        self._lock = asyncio.Lock()
        self._fallback: _McpHttpFallback | None = None

    async def _ensure_sdk_session(self) -> Any:
        if self._session is not None:
            return self._session
        async with self._lock:
            if self._session is not None:
                return self._session
            if not MCP_SDK_AVAILABLE:
                raise RuntimeError(f"MCP SDK unavailable: {MCP_SDK_ERROR}")
            stack = AsyncExitStack()
            try:
                if _STREAMABLE_V1 is not None:
                    streams = await stack.enter_async_context(
                        _STREAMABLE_V1(self._url, headers=self._headers)
                    )
                else:
                    import httpx2  # type: ignore

                    http_client = httpx2.AsyncClient(headers=self._headers)
                    await stack.enter_async_context(http_client)
                    streams = await stack.enter_async_context(
                        _STREAMABLE_V2(self._url, http_client=http_client)
                    )
                read, write = streams[0], streams[1]
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
            except Exception:
                await stack.aclose()
                raise
            self._stack = stack
            self._session = session
            return session

    async def _reset_sdk_session(self) -> None:
        self._session = None
        if self._stack is not None:
            try:
                await self._stack.aclose()
            except Exception:
                pass
            self._stack = None

    async def _search_sdk(self, request: SearchRequest) -> SearchBatch:
        started = time.perf_counter()
        for attempt in (1, 2):
            try:
                session = await self._ensure_sdk_session()
                result = await session.call_tool("SearchPro", arguments=request.to_mcp_args())
                return normalize_mcp_result(
                    result,
                    self.name,
                    (time.perf_counter() - started) * 1000,
                    request,
                )
            except Exception as exc:  # session expiry / transport
                await self._reset_sdk_session()
                if attempt == 2:
                    return SearchBatch(
                        provider=self.name,
                        latency_ms=(time.perf_counter() - started) * 1000,
                        error=f"MCP SDK error: {type(exc).__name__}: {exc}",
                        error_kind="transport",
                        request=request,
                        query=request.query,
                    )
        return SearchBatch(provider=self.name, error="MCP SDK error", error_kind="transport")

    async def _search_fallback(self, request: SearchRequest) -> SearchBatch:
        if self._fallback is None:
            self._fallback = _McpHttpFallback(self._url, self._headers)
        started = time.perf_counter()
        try:
            result = await self._fallback.call_tool("SearchPro", request.to_mcp_args())
        except Exception as exc:
            return SearchBatch(
                provider=self.name,
                latency_ms=(time.perf_counter() - started) * 1000,
                error=f"MCP HTTP error: {type(exc).__name__}: {exc}",
                error_kind="transport",
                request=request,
                query=request.query,
            )
        return normalize_mcp_result(
            result,
            self.name,
            (time.perf_counter() - started) * 1000,
            request,
        )

    async def search(self, request: SearchRequest) -> SearchBatch:
        if not self.settings.search_api_key:
            return SearchBatch(
                provider=self.name,
                error="MCP key is not configured",
                error_kind="auth",
                request=request,
                query=request.query,
            )
        if MCP_SDK_AVAILABLE:
            batch = await self._search_sdk(request)
            if batch.ok or batch.error_kind not in {"transport", "server"}:
                return batch
            # The SDK path failed before producing a usable result; the
            # built-in JSON-RPC client is an independent transport and is the
            # documented fallback for session/protocol differences.
            return await self._search_fallback(request)
        return await self._search_fallback(request)

    async def health(self) -> ProviderHealth:
        mode = "sdk" if MCP_SDK_AVAILABLE else "http-jsonrpc fallback"
        return ProviderHealth(
            provider=self.name,
            configured=bool(self.settings.search_api_key),
            available=bool(self.settings.search_api_key),
            detail=f"POST /Mcp ({mode}); no live call in health check",
        )

    async def close(self) -> None:
        await self._reset_sdk_session()
        if self._fallback is not None:
            await self._fallback.close()


class _McpHttpFallback:
    """Minimal MCP Streamable HTTP client for a single tool.

    Covers initialize -> notifications/initialized -> tools/call, captures
    Mcp-Session-Id, and accepts either application/json or SSE responses.
    """

    def __init__(self, url: str, headers: dict[str, str]) -> None:
        self.url = url
        self._headers = dict(headers)
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=8.0))
        self._session_id: str | None = None
        self._next_id = 1
        self._initialized = False

    async def _post(self, payload: dict[str, Any], expect_response: bool) -> dict[str, Any] | None:
        headers = dict(self._headers)
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        response = await self._client.post(self.url, json=payload, headers=headers)
        session_id = response.headers.get("Mcp-Session-Id")
        if session_id:
            self._session_id = session_id
        if not expect_response:
            return None
        if response.status_code >= 400:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
        content_type = response.headers.get("Content-Type", "")
        if "text/event-stream" in content_type:
            return self._parse_sse(response.text, payload.get("id"))
        data = response.json()
        if "error" in data:
            raise RuntimeError(f"MCP error: {data['error']}")
        return data

    @staticmethod
    def _parse_sse(text: str, request_id: Any) -> dict[str, Any]:
        messages: list[dict[str, Any]] = []
        for block in text.split("\n\n"):
            data_lines = [
                line[5:].strip()
                for line in block.splitlines()
                if line.startswith("data:")
            ]
            if not data_lines:
                continue
            try:
                message = json.loads("\n".join(data_lines))
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict):
                messages.append(message)
        for message in messages:
            if message.get("id") == request_id and "result" in message:
                return message
        for message in messages:
            if "result" in message:
                return message
        raise RuntimeError("SSE response did not contain a JSON-RPC result")

    async def initialize(self) -> None:
        if self._initialized:
            return
        request_id = self._next_id
        self._next_id += 1
        await self._post(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "claimlab", "version": "0.1.0"},
                },
            },
            expect_response=True,
        )
        await self._post(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            expect_response=False,
        )
        self._initialized = True

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        await self.initialize()
        request_id = self._next_id
        self._next_id += 1
        response = await self._post(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
            expect_response=True,
        )
        if not response or "result" not in response:
            raise RuntimeError("MCP tools/call returned no result")
        return response["result"]

    async def close(self) -> None:
        await self._client.aclose()
