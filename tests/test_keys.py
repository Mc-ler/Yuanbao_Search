import json
from pathlib import Path

import pytest

from claimlab.config import Settings
from claimlab.keys import (
    LLMConfigError,
    LLMProvider,
    bearer_auth_header,
    choose_model,
    key_info,
    load_llm_registry,
    normalize_base_url,
    select_llm,
    strip_bearer,
)
from claimlab.llm.client import OpenAICompatLLM


def test_bearer_raw_key():
    assert bearer_auth_header("sk-abc") == "Bearer sk-abc"


def test_bearer_already_prefixed_is_not_doubled():
    assert bearer_auth_header("Bearer sk-abc") == "Bearer sk-abc"
    assert bearer_auth_header("bearer   sk-abc") == "Bearer sk-abc"
    assert bearer_auth_header("  Bearer sk-abc  ") == "Bearer sk-abc"


def test_bearer_empty():
    assert bearer_auth_header("") == ""
    assert bearer_auth_header(None) == ""
    assert strip_bearer("Bearer ") == ""


def test_key_info_never_contains_value():
    info = key_info("Bearer sk-secret")
    assert info["present"] is True
    assert info["length"] == len("sk-secret")
    assert info["had_bearer_prefix"] is True
    assert "sk-secret" not in json.dumps(info)


def test_toklens_base_url_gets_v1():
    assert normalize_base_url("https://lax.toklens.ai") == "https://lax.toklens.ai/v1"
    assert normalize_base_url("https://lax.toklens.ai/") == "https://lax.toklens.ai/v1"
    assert normalize_base_url("https://lax.toklens.ai/v1/") == "https://lax.toklens.ai/v1"


def provider() -> LLMProvider:
    return LLMProvider(
        name="gpt",
        label="GPT",
        base_url="https://lax.toklens.ai/v1",
        api_key="sk-test",
        preferred_models=["gpt-4o", "gpt-4o-mini"],
        default_model="gpt-4o",
    )


def test_choose_model_explicit_available():
    assert choose_model(provider(), "gpt-4o-mini", ["gpt-4o-mini", "gpt-4o"]) == "gpt-4o-mini"


def test_choose_model_requested_missing_falls_back_to_preferred():
    assert choose_model(provider(), "gpt-4.1", ["gpt-4o-mini"]) == "gpt-4o-mini"


def test_choose_model_auto_prefers_preferred():
    assert choose_model(provider(), "", ["gpt-4o-mini", "gpt-4.1"]) == "gpt-4o-mini"


def test_choose_model_matches_prefixed_catalog_ids():
    assert choose_model(provider(), "gpt-4o", ["openai/gpt-4o"]) == "openai/gpt-4o"


def test_choose_model_without_catalog_uses_default():
    assert choose_model(provider(), "", []) == "gpt-4o"


def _write_config(tmp_path: Path) -> Path:
    path = tmp_path / "llm_providers.json"
    path.write_text(
        json.dumps(
            {
                "default_provider": "gpt",
                "providers": {
                    "gpt": {
                        "base_url": "https://lax.toklens.ai/v1",
                        "api_key_env": "TEST_GPT_KEY",
                        "preferred_models": ["gpt-4o", "gpt-4o-mini"],
                        "default_model": "gpt-4o",
                    },
                    "codex": {
                        "base_url": "https://lax.toklens.ai/v1",
                        "api_key_env": "TEST_CODEX_KEY",
                        "preferred_models": ["codex-mini-latest"],
                        "default_model": "codex-mini-latest",
                    },
                },
                "task_routes": {"extract_claims": "gpt", "match_evidence": "gpt", "code": "codex"},
            }
        ),
        encoding="utf-8",
    )
    return path


def _settings(tmp_path: Path, path: Path) -> Settings:
    return Settings(
        config_dir=tmp_path,
        llm_providers_path=path,
        cache_dir=tmp_path / "cache",
        archive_dir=tmp_path / "archive",
        state_dir=tmp_path / "state",
        fixtures_dir=tmp_path / "fixtures",
        web_dir=tmp_path / "web",
        llm_api_key="",
        llm_model="",
        llm_provider="",
    )


def test_registry_routes_and_selects_model(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_GPT_KEY", "sk-gpt")
    monkeypatch.setenv("TEST_CODEX_KEY", "sk-codex")
    path = _write_config(tmp_path)
    settings = _settings(tmp_path, path)
    registry = load_llm_registry(settings)
    assert registry.has_any_key
    assert registry.provider_for("extract_claims").name == "gpt"
    assert registry.provider_for("code").name == "codex"
    assert registry.provider_for("unknown").name == "gpt"
    selection = select_llm(settings, registry, "extract_claims", available_models=["gpt-4o-mini"])
    assert selection.provider.name == "gpt"
    assert selection.model == "gpt-4o-mini"


def test_registry_explicit_model_override(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_GPT_KEY", "sk-gpt")
    path = _write_config(tmp_path)
    settings = _settings(tmp_path, path)
    settings.llm_model = "gpt-4.1"
    registry = load_llm_registry(settings)
    selection = select_llm(settings, registry, "extract_claims", available_models=["gpt-4.1", "gpt-4o"])
    assert selection.model == "gpt-4.1"


def test_registry_without_keys_raises(tmp_path, monkeypatch):
    for name in ("TOKLENS_API_KEY", "LLM_API_KEY", "GPT_API_KEY", "CODEX_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    path = _write_config(tmp_path)
    settings = _settings(tmp_path, path)
    registry = load_llm_registry(settings)
    assert not registry.has_any_key
    with pytest.raises(LLMConfigError):
        select_llm(settings, registry, "extract_claims")


def test_legacy_single_provider_normalizes_toklens(tmp_path):
    settings = Settings(
        config_dir=tmp_path,
        llm_providers_path=tmp_path / "missing.json",
        cache_dir=tmp_path / "cache",
        archive_dir=tmp_path / "archive",
        state_dir=tmp_path / "state",
        fixtures_dir=tmp_path / "fixtures",
        web_dir=tmp_path / "web",
        llm_api_key="sk-legacy",
        llm_model="gpt-4o",
        llm_base_url="https://lax.toklens.ai",
    )
    registry = load_llm_registry(settings)
    assert registry.legacy
    provider = next(iter(registry.providers.values()))
    assert provider.base_url == "https://lax.toklens.ai/v1"
    assert provider.key_present
    assert provider.default_model == "gpt-4o"


def test_llm_describe_has_provider_without_key(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_GPT_KEY", "sk-gpt")
    path = _write_config(tmp_path)
    settings = _settings(tmp_path, path)
    registry = load_llm_registry(settings)
    llm = OpenAICompatLLM(settings, registry)
    described = llm.describe()
    assert described["key_present"] is True
    assert described["provider"] == "gpt"
    assert "sk-gpt" not in json.dumps(described)
