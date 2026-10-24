from pathlib import Path

from fastapi.testclient import TestClient

from claimlab.api import create_app
from claimlab.config import Settings
from claimlab.llm.client import FakeLLM
from claimlab.runtime import Sandbox
from claimlab.search.fake import FakeSearchProvider


def make_app(tmp_path: Path):
    settings = Settings(
        search_provider="fake",
        search_api_key="",
        llm_api_key="",
        allow_fake_search=True,
        screenshot_enabled=False,
        root=tmp_path,
        cache_dir=tmp_path / "cache",
        archive_dir=tmp_path / "archive",
        state_dir=tmp_path / "state",
        config_dir=Path("config").resolve(),
        fixtures_dir=Path("fixtures").resolve(),
        web_dir=Path("web").resolve(),
    )
    settings.ensure_dirs()
    sandbox = Sandbox(settings, {"fake": FakeSearchProvider([])}, {}, FakeLLM())
    return create_app(settings, sandbox), settings


def test_llm_config_writes_env_and_rebuilds(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    app, settings = make_app(tmp_path)
    client = TestClient(app)
    response = client.post(
        "/api/config/llm",
        json={
            "provider": "deepseek",
            "api_key": "sk-test-key",
            "base_url": "http://127.0.0.1:9/v1",
            "model": "deepseek-flash",
        },
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "DEEPSEEK_API_KEY=sk-test-key" in env_text
    assert "LLM_PROVIDER=deepseek" in env_text
    assert env_text.count("DEEPSEEK_API_KEY=") == 1


def test_search_and_screenshot_config_status(tmp_path, monkeypatch):
    monkeypatch.setenv("SEARCH_API_KEY", "")
    app, settings = make_app(tmp_path)
    client = TestClient(app)
    response = client.post("/api/config/search", json={"api_key": "search-test", "base_url": "https://api.example.com"})
    assert response.status_code == 200
    assert response.json()["key_present"] is True
    screenshot = client.post("/api/config/screenshots", json={"enabled": False})
    assert screenshot.status_code == 200
    assert screenshot.json()["enabled"] is False
