"""OpenAI-compatible chat client with provider-aware keys and model selection.

Providers come from ``config/llm_providers.json`` (GPT/Codex via the Toklens
third-party supplier by default). Each provider resolves its own key from
``.env`` / the process environment. The model is chosen from the provider's
preferred list, the live ``/models`` catalog, and an optional explicit
``LLM_MODEL`` override. Yuanbao Search and LLM auth both normalize to exactly
one ``Bearer`` prefix.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict
from typing import Any, Protocol

import httpx

from ..config import Settings
from ..contracts import Claim, ResearchTask, SearchPage
from ..keys import (
    LLMConfigError,
    LLMProvider,
    LLMRegistry,
    bearer_auth_header,
    load_llm_registry,
    select_llm,
)
from ..search.cache import DiskCache, cache_key


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    async def json(
        self,
        task: str,
        payload: dict[str, Any],
        system_prompt: str = "",
        model: str | None = None,
        images: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]: ...

    async def close(self) -> None: ...

    def describe(self) -> dict[str, Any]: ...


def _extract_json(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        parsed = json.loads(raw[start : end + 1])
        if isinstance(parsed, dict):
            return parsed
    raise LLMError("model did not return a JSON object")


def _is_model_error(status_code: int, text: str) -> bool:
    lowered = (text or "").lower()
    if status_code == 404:
        return True
    if status_code not in (400, 404):
        return False
    return "model" in lowered and any(
        marker in lowered
        for marker in ("not found", "does not exist", "invalid", "unsupported", "unknown model", "no such model")
    )


def _is_chat_model(model: str) -> bool:
    lowered = (model or "").lower()
    return not any(marker in lowered for marker in ("image", "embedding", "tts", "whisper", "audio", "video", "moderation"))


def _is_vision_error(status_code: int, text: str) -> bool:
    lowered = (text or "").lower()
    if status_code not in (400, 422):
        return False
    return any(marker in lowered for marker in ("image", "vision", "multimodal", "content type"))


class OpenAICompatLLM:
    def __init__(self, settings: Settings, registry: LLMRegistry | None = None) -> None:
        self.settings = settings
        self.registry = registry or load_llm_registry(settings)
        self.model = settings.llm_model
        self._cache = DiskCache(settings.cache_dir, "llm", settings.cache_ttl_hours * 3600)
        self._clients: dict[str, httpx.AsyncClient] = {}
        self._models: dict[str, list[str]] = {}
        self._selected: dict[tuple[str, str], str] = {}
        self._model_lock = asyncio.Lock()
        self._vision_disabled: set[str] = set()
        self.last_vision_used = False
        self.calls = 0
        self.cache_hits = 0

    def _client_for(self, provider: LLMProvider) -> httpx.AsyncClient:
        client = self._clients.get(provider.name)
        if client is not None:
            return client
        headers = {"Content-Type": "application/json", **provider.headers}
        auth = bearer_auth_header(provider.api_key)
        if auth:
            headers["Authorization"] = auth
        client = httpx.AsyncClient(
            base_url=provider.base_url,
            timeout=httpx.Timeout(60.0, connect=10.0),
            headers=headers,
        )
        self._clients[provider.name] = client
        return client

    async def _list_models(self, provider: LLMProvider) -> list[str]:
        if provider.name in self._models:
            return self._models[provider.name]
        async with self._model_lock:
            if provider.name in self._models:
                return self._models[provider.name]
            models: list[str] = []
            try:
                response = await self._client_for(provider).get("/models")
                if response.status_code == 200:
                    data = response.json()
                    models = [
                        str(item.get("id"))
                        for item in data.get("data", [])
                        if isinstance(item, dict) and item.get("id")
                    ]
            except Exception:
                models = []
            self._models[provider.name] = models
            return models

    def _provider_for(self, task: str) -> LLMProvider:
        provider = self.registry.provider_for(task, self.settings.llm_provider or None)
        if provider is None or not provider.key_present:
            provider = next((item for item in self.registry.providers.values() if item.key_present), None)
        if provider is None:
            raise LLMConfigError(
                "no LLM key configured; set GPT_API_KEY / CODEX_API_KEY / TOKLENS_API_KEY (or LLM_API_KEY)"
            )
        return provider

    async def _resolve(self, task: str, model_hint: str | None) -> tuple[LLMProvider, str, list[str]]:
        provider = self._provider_for(task)
        available = await self._list_models(provider)
        hint = model_hint or self._selected.get((provider.name, task)) or ""
        selection = select_llm(
            self.settings,
            self.registry,
            task,
            requested_provider=provider.name,
            model_hint=hint,
            available_models=available,
        )
        if not selection.model:
            raise LLMError(f"no model resolved for provider {provider.name}")
        return selection.provider, selection.model, available

    @staticmethod
    def _image_hashes(images: list[dict[str, Any]] | None) -> list[str]:
        return [
            hashlib.sha256(str(image.get("data_url") or image.get("url") or "").encode("utf-8")).hexdigest()
            for image in (images or [])
        ]

    @staticmethod
    def _messages(
        payload: dict[str, Any],
        system_prompt: str,
        images: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        text = (
            "输入数据（JSON）：\n"
            + json.dumps(payload, ensure_ascii=False)
            + "\n只返回 JSON 对象，不要解释。"
        )
        content: Any = text
        if images:
            content = [{"type": "text", "text": text}]
            for image in images:
                url = image.get("data_url") or image.get("url") or ""
                if url:
                    content.append({"type": "image_url", "image_url": {"url": url}})
        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": content})
        return messages

    async def json(
        self,
        task: str,
        payload: dict[str, Any],
        system_prompt: str = "",
        model: str | None = None,
        images: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        provider, chosen_model, available = await self._resolve(task, model)
        images = [image for image in (images or []) if image.get("data_url") or image.get("url")]
        use_images = bool(images) and provider.vision and provider.name not in self._vision_disabled
        image_keys = self._image_hashes(images) if use_images else []
        key = cache_key("llm", provider.name, chosen_model, task, system_prompt, payload, image_keys)
        text_key = cache_key("llm", provider.name, chosen_model, task, system_prompt, payload)
        cached = self._cache.get(key if use_images else text_key)
        if cached is not None:
            self.cache_hits += 1
            self.last_vision_used = use_images
            return cached

        messages = self._messages(payload, system_prompt, images if use_images else None)
        candidates: list[str] = []
        if available:
            # /models is the live catalog. Never let stale preferred names
            # (e.g. gpt-4.1) crowd out a catalog model that actually works.
            candidates = [chosen_model, *[m for m in available if _is_chat_model(m)]]
        else:
            candidates = [chosen_model, *provider.preferred_models, provider.default_model]
        deduped: list[str] = []
        for candidate in candidates:
            if candidate and candidate not in deduped:
                deduped.append(candidate)
        candidates = deduped[:8]

        client = self._client_for(provider)
        last_error = ""
        for index, candidate in enumerate(candidates):
            body: dict[str, Any] = {
                "model": candidate,
                "messages": messages,
                "temperature": 0,
                "max_tokens": 1200,
                "response_format": {"type": "json_object"},
            }
            self.calls += 1
            try:
                response = await client.post("/chat/completions", json=body)
            except httpx.HTTPError as exc:
                last_error = f"transport: {type(exc).__name__}"
                if index + 1 < len(candidates):
                    continue
                raise LLMError(last_error) from exc
            if response.status_code in (400, 422):
                body.pop("response_format", None)
                self.calls += 1
                response = await client.post("/chat/completions", json=body)
            if response.status_code >= 400 and use_images and _is_vision_error(response.status_code, response.text):
                # The provider rejected image content. Disable vision for this
                # provider and retry the same candidate with text-only input.
                self._vision_disabled.add(provider.name)
                use_images = False
                key = text_key
                messages = self._messages(payload, system_prompt, None)
                body["messages"] = messages
                body.pop("response_format", None)
                self.calls += 1
                response = await client.post("/chat/completions", json=body)
            if response.status_code >= 400:
                last_error = f"HTTP {response.status_code}: {response.text[:300]}"
                retryable = _is_model_error(response.status_code, response.text) or response.status_code == 429
                if retryable and index + 1 < len(candidates):
                    continue
                raise LLMError(last_error)
            data = response.json()
            try:
                content = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise LLMError("unexpected LLM response shape") from exc
            parsed = _extract_json(content)
            self._selected[(provider.name, task)] = candidate
            self.model = candidate
            self.last_vision_used = use_images
            self._cache.set(key, parsed)
            return parsed
        raise LLMError(last_error or "LLM request failed")

    def describe(self) -> dict[str, Any]:
        public = self.registry.public()
        selection = next(iter(self._selected.items()), None)
        if selection is not None:
            (provider_name, _task), model = selection
        else:
            provider = self.registry.provider_for("", self.settings.llm_provider or None)
            provider_name = provider.name if provider else self.registry.default_provider
            if provider is not None:
                model = (
                    provider.default_model
                    or (provider.preferred_models[0] if provider.preferred_models else "")
                    or self.settings.llm_model
                )
            else:
                model = self.settings.llm_model
        return {
            "type": "openai-compatible",
            "key_present": self.registry.has_any_key,
            "provider": provider_name or None,
            "model": model or None,
            "providers": public["providers"],
            "default_provider": public["default_provider"],
            "task_routes": public["task_routes"],
            "vision": any(item.get("vision") for item in public["providers"]),
            "vision_disabled": sorted(self._vision_disabled),
            "last_vision_used": self.last_vision_used,
        }

    async def close(self) -> None:
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()


class FakeLLM:
    """Deterministic offline substitute used by tests."""

    def __init__(self) -> None:
        self.calls = 0
        self.cache_hits = 0

    async def json(
        self,
        task: str,
        payload: dict[str, Any],
        system_prompt: str = "",
        model: str | None = None,
        images: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self.calls += 1
        if task == "extract_claims":
            from ..skills.extraction import heuristic_extract

            result = heuristic_extract(
                ResearchTask(text=str(payload.get("text") or ""))
            )
            return {
                "subject": result.subject,
                "facts": [asdict(item) for item in result.facts],
                "emotions": [asdict(item) for item in result.emotions],
                "dropped": result.dropped,
            }
        if task == "match_evidence":
            from ..skills.matching import heuristic_match

            claim_data = payload.get("claim") or {}
            claim = Claim(
                claim_id="fake-claim",
                type="fact",
                text=str(claim_data.get("text") or ""),
                field=str(claim_data.get("field") or "unknown"),
                value=claim_data.get("value"),
            )
            matches = []
            for item in payload.get("evidence") or []:
                page = SearchPage(
                    title=str(item.get("title") or ""),
                    site=str(item.get("site") or ""),
                    date=item.get("date"),
                    passage=str(item.get("passage") or ""),
                )
                match = heuristic_match(claim, page)
                matches.append(
                    {
                        "evidence_id": item.get("evidence_id"),
                        "relation": match.relation,
                        "quote": match.quote,
                        "observed_value": match.observed_value,
                        "reason": "heuristic",
                    }
                )
            return {"matches": matches}
        return {}

    def describe(self) -> dict[str, Any]:
        return {
            "type": "heuristic",
            "key_present": False,
            "provider": None,
            "model": None,
            "providers": [],
            "default_provider": None,
            "task_routes": {},
            "vision": False,
            "vision_disabled": [],
            "last_vision_used": False,
        }

    async def close(self) -> None:
        return None


def build_llm(settings: Settings) -> LLMClient:
    registry = load_llm_registry(settings)
    if not registry.has_any_key:
        return FakeLLM()
    return OpenAICompatLLM(settings, registry)
