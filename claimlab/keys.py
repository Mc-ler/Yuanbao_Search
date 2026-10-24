"""Central key/auth and LLM provider resolution.

Two rules live here so every entry point behaves the same way:

1. Yuanbao Search accepts the raw service key. The Authorization header is
   built as exactly one ``Bearer <key>``; a key already stored with a Bearer
   prefix is normalized instead of double-prefixed.
2. LLM calls are routed to a third-party provider (Toklens by default) using a
   provider registry. Keys are resolved per provider, and the model is chosen
   from the provider's preferred list + the live /models catalog.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .config import Settings

BEARER_PREFIX_RE = re.compile(r"(?i)^\s*bearer\s+")
KNOWN_LLM_KEY_ENVS = ("LLM_API_KEY", "GPT_API_KEY", "CODEX_API_KEY", "TOKLENS_API_KEY")


class LLMConfigError(RuntimeError):
    pass


def strip_bearer(value: str | None) -> str:
    raw = (value or "").strip()
    if raw.lower() == "bearer":
        return ""
    return BEARER_PREFIX_RE.sub("", raw).strip()


def bearer_auth_header(value: str | None) -> str:
    key = strip_bearer(value)
    return f"Bearer {key}" if key else ""


def key_info(value: str | None) -> dict[str, Any]:
    raw = strip_bearer(value)
    return {
        "present": bool(raw),
        "length": len(raw),
        "had_bearer_prefix": bool(value and BEARER_PREFIX_RE.match(value.strip())),
    }


def normalize_base_url(value: str | None) -> str:
    url = (value or "").strip().rstrip("/")
    if not url:
        return ""
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    # The Toklens documentation's base URL includes /v1. A legacy .env value
    # without it is a common failure mode; normalize only the bare host.
    if parts.hostname == "lax.toklens.ai" and parts.path in ("", "/"):
        url = url + "/v1"
    return url


def safe_base_url(value: str | None) -> str:
    try:
        parts = urlsplit((value or "").strip())
        if parts.scheme and parts.hostname:
            netloc = parts.hostname
            if parts.port:
                netloc = f"{netloc}:{parts.port}"
            return urlunsplit((parts.scheme, netloc, parts.path.rstrip("/"), "", ""))
    except ValueError:
        pass
    return (value or "").strip()


def _env(name: str | None) -> str:
    return os.environ.get(name, "").strip() if name else ""


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


@dataclass
class LLMProvider:
    name: str
    label: str
    base_url: str
    api_key: str = ""
    preferred_models: list[str] = field(default_factory=list)
    default_model: str = ""
    task_models: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def key_present(self) -> bool:
        return bool(strip_bearer(self.api_key))

    def public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "base_url": safe_base_url(self.base_url),
            "key_present": self.key_present,
            "key_length": len(strip_bearer(self.api_key)),
            "preferred_models": list(self.preferred_models),
            "default_model": self.default_model or None,
        }


@dataclass
class LLMSelection:
    provider: LLMProvider
    model: str


@dataclass
class LLMRegistry:
    providers: dict[str, LLMProvider]
    default_provider: str
    task_routes: dict[str, str] = field(default_factory=dict)
    task_models: dict[str, str] = field(default_factory=dict)
    legacy: bool = False

    @property
    def has_any_key(self) -> bool:
        return any(provider.key_present for provider in self.providers.values())

    def provider_for(self, task: str, requested: str | None = None) -> LLMProvider | None:
        if requested and requested in self.providers:
            return self.providers[requested]
        routed = self.task_routes.get(task)
        if routed and routed in self.providers:
            return self.providers[routed]
        if self.default_provider in self.providers:
            return self.providers[self.default_provider]
        for provider in self.providers.values():
            if provider.key_present:
                return provider
        return next(iter(self.providers.values()), None)

    def public(self) -> dict[str, Any]:
        return {
            "default_provider": self.default_provider,
            "legacy": self.legacy,
            "task_routes": dict(self.task_routes),
            "providers": [provider.public() for provider in self.providers.values()],
        }


def load_llm_registry(settings: Settings, config_path: Path | None = None) -> LLMRegistry:
    path = config_path or settings.llm_providers_path
    data = _load_json(path)
    raw_providers = data.get("providers")
    providers: dict[str, LLMProvider] = {}
    if isinstance(raw_providers, dict):
        for raw_name, raw in raw_providers.items():
            if not isinstance(raw, dict):
                continue
            name = str(raw_name).strip()
            if not name:
                continue
            base_url = _env(raw.get("base_url_env")) or str(raw.get("base_url") or "") or settings.llm_base_url
            api_key = (
                _env(raw.get("api_key_env"))
                or _env(raw.get("fallback_key_env"))
                or settings.llm_api_key
                or _env("TOKLENS_API_KEY")
            )
            preferred = [str(item).strip() for item in (raw.get("preferred_models") or []) if str(item).strip()]
            default_model = str(raw.get("default_model") or (preferred[0] if preferred else "") or settings.llm_model)
            providers[name] = LLMProvider(
                name=name,
                label=str(raw.get("label") or name),
                base_url=normalize_base_url(base_url),
                api_key=api_key,
                preferred_models=preferred,
                default_model=default_model,
                task_models={
                    str(key): str(value) for key, value in (raw.get("task_models") or {}).items()
                },
                headers={str(key): str(value) for key, value in (raw.get("headers") or {}).items()},
            )

    legacy = False
    if not providers:
        legacy = True
        name = settings.llm_provider or "default"
        api_key = (
            settings.llm_api_key
            or _env("TOKLENS_API_KEY")
            or _env("GPT_API_KEY")
            or _env("CODEX_API_KEY")
        )
        preferred = [settings.llm_model] if settings.llm_model else []
        providers[name] = LLMProvider(
            name=name,
            label="legacy OpenAI-compatible endpoint",
            base_url=normalize_base_url(settings.llm_base_url),
            api_key=api_key,
            preferred_models=preferred,
            default_model=settings.llm_model,
        )

    default_provider = settings.llm_provider or str(data.get("default_provider") or "")
    if default_provider not in providers:
        default_provider = next(iter(providers))
    return LLMRegistry(
        providers=providers,
        default_provider=default_provider,
        task_routes={str(key): str(value) for key, value in (data.get("task_routes") or {}).items()},
        task_models={str(key): str(value) for key, value in (data.get("task_models") or {}).items()},
        legacy=legacy,
    )


def _model_match(available: list[str], name: str) -> str | None:
    if not name:
        return None
    if not available:
        return name
    for model in available:
        if model == name:
            return model
    lower = name.lower()
    for model in available:
        lowered = model.lower()
        if lowered == lower or lowered.endswith("/" + lower) or lowered.endswith(":" + lower):
            return model
    return None


def choose_model(
    provider: LLMProvider,
    requested: str | None = None,
    available_models: list[str] | None = None,
) -> str:
    available = [str(item).strip() for item in (available_models or []) if str(item).strip()]
    requested = (requested or "").strip()
    if requested:
        matched = _model_match(available, requested)
        if matched:
            return matched
    for candidate in provider.preferred_models:
        matched = _model_match(available, candidate)
        if matched:
            return matched
    if provider.default_model:
        matched = _model_match(available, provider.default_model)
        if matched:
            return matched
    if available:
        return available[0]
    return requested or provider.default_model or (provider.preferred_models[0] if provider.preferred_models else "")


def select_llm(
    settings: Settings,
    registry: LLMRegistry,
    task: str,
    requested_provider: str | None = None,
    model_hint: str | None = None,
    available_models: list[str] | None = None,
) -> LLMSelection:
    provider = registry.provider_for(task, requested_provider or settings.llm_provider or None)
    if provider is None:
        raise LLMConfigError("no LLM provider configured")
    if not provider.key_present:
        provider = next((item for item in registry.providers.values() if item.key_present), None)
        if provider is None:
            raise LLMConfigError(
                "no LLM key configured; set GPT_API_KEY / CODEX_API_KEY / TOKLENS_API_KEY (or LLM_API_KEY)"
            )
    requested_model = (
        model_hint
        or settings.llm_model
        or registry.task_models.get(task)
        or provider.task_models.get(task)
        or ""
    )
    model = choose_model(provider, requested_model, available_models)
    return LLMSelection(provider=provider, model=model)
