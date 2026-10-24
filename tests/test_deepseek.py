import json
from pathlib import Path

from claimlab.config import Settings
from claimlab.keys import load_llm_registry, select_llm


def write_config(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "default_provider": "deepseek",
                "providers": {
                    "deepseek": {
                        "base_url": "https://api.deepseek.com/v1",
                        "api_key_env": "TEST_DEEPSEEK_KEY",
                        "preferred_models": ["deepseek-chat", "deepseek-reasoner"],
                        "default_model": "deepseek-chat",
                        "timeout_seconds": 90,
                        "legacy_key": False,
                    },
                    "gpt": {
                        "base_url": "https://lax.toklens.ai/v1",
                        "api_key_env": "TEST_GPT_KEY",
                        "default_model": "gpt-5.6-sol",
                    },
                },
                "task_routes": {"answer": "deepseek", "extract_claims": "gpt"},
            }
        ),
        encoding="utf-8",
    )
    return path


def settings_for(tmp_path: Path, config: Path) -> Settings:
    return Settings(
        config_dir=tmp_path,
        llm_providers_path=config,
        cache_dir=tmp_path / "cache",
        archive_dir=tmp_path / "archive",
        state_dir=tmp_path / "state",
        fixtures_dir=tmp_path / "fixtures",
        web_dir=tmp_path / "web",
        llm_api_key="",
        llm_model="",
        llm_provider="",
    )


def test_deepseek_is_default_and_routes(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_DEEPSEEK_KEY", "sk-deepseek")
    config = write_config(tmp_path / "llm_providers.json")
    settings = settings_for(tmp_path, config)
    registry = load_llm_registry(settings)
    assert registry.default_provider == "deepseek"
    assert registry.provider_for("answer").name == "deepseek"
    assert registry.provider_for("extract_claims").name == "gpt"
    assert registry.providers["deepseek"].key_present
    assert registry.providers["deepseek"].timeout_seconds == 90
    selection = select_llm(settings, registry, "answer", available_models=["deepseek-chat"])
    assert selection.provider.name == "deepseek"
    assert selection.model == "deepseek-chat"


def test_deepseek_never_inherits_legacy_toklens_key(tmp_path):
    config = write_config(tmp_path / "llm_providers.json")
    settings = settings_for(tmp_path, config)
    settings.llm_api_key = "sk-legacy-toklens"
    registry = load_llm_registry(settings)
    assert registry.providers["deepseek"].key_present is False
    assert registry.providers["gpt"].key_present is True


def test_deepseek_missing_key_falls_back(tmp_path, monkeypatch):
    for name in ("TEST_DEEPSEEK_KEY", "TEST_GPT_KEY"):
        monkeypatch.delenv(name, raising=False)
    config = write_config(tmp_path / "llm_providers.json")
    settings = settings_for(tmp_path, config)
    registry = load_llm_registry(settings)
    assert not registry.has_any_key
    provider = registry.provider_for("answer")
    assert provider.name == "deepseek"