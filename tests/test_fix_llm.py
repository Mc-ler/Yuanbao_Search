import json
from pathlib import Path

from scripts import fix_llm


class FakeResponse:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data

    def json(self):
        if isinstance(self._data, Exception):
            raise self._data
        return self._data


def test_verify_model_requires_exact_json_ok_and_retries_only_response_format():
    calls = []

    class Client:
        def post(self, path, json):
            calls.append(json)
            if len(calls) == 1:
                return FakeResponse(400, {"error": {"type": "invalid_request_error", "param": "response_format", "message": "unsupported"}})
            return FakeResponse(200, {"choices": [{"message": {"content": '{"ok": true}'}}]})

    assert fix_llm.verify_model(Client(), "gpt-6-astra") == (True, "HTTP 200/json_ok_true")
    assert len(calls) == 2
    assert calls[0]["model"] == calls[1]["model"] == "gpt-6-astra"
    assert "response_format" not in calls[1]


def test_verify_model_does_not_fallback_on_model_not_found():
    calls = []

    class Client:
        def post(self, path, json):
            calls.append(json["model"])
            return FakeResponse(404, {"error": {"type": "model_not_found", "message": "secret detail"}})

    ok, detail = fix_llm.verify_model(Client(), "gpt-6-astra")
    assert not ok
    assert detail == "HTTP 404/model_not_found"
    assert calls == ["gpt-6-astra"]


def test_catalog_requires_exact_id():
    class Client:
        def get(self, path):
            return FakeResponse(200, {"data": [{"id": "vendor/gpt-6-astra"}]})

    assert fix_llm.catalog_has_exact_model(Client(), "gpt-6-astra")[0] is False


def test_persist_preserves_env_and_updates_selected_provider(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("# keep me\nOTHER=value=with=equals\nLLM_MODEL=old\n", encoding="utf-8")
    config = tmp_path / "llm_providers.json"
    config.write_text(json.dumps({"default_provider": "gpt", "providers": {"gpt": {"preferred_models": ["old", "other"], "default_model": "old"}, "codex": {"default_model": "c"}}}), encoding="utf-8")

    fix_llm.persist("gpt", "gpt-6-astra", ["old", "other"], env_path=env, config_path=config)

    assert env.read_text(encoding="utf-8") == "# keep me\nOTHER=value=with=equals\nLLM_MODEL=gpt-6-astra\nLLM_PROVIDER=gpt\n"
    data = json.loads(config.read_text(encoding="utf-8"))
    assert data["providers"]["gpt"]["default_model"] == "gpt-6-astra"
    assert data["providers"]["gpt"]["preferred_models"] == ["gpt-6-astra", "old", "other"]
    assert data["providers"]["codex"]["default_model"] == "c"
