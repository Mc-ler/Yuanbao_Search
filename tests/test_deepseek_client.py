import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from claimlab.config import Settings
from claimlab.llm.client import OpenAICompatLLM
from claimlab.keys import load_llm_registry


class Handler(BaseHTTPRequestHandler):
    calls = []
    fail_once = False

    def log_message(self, *args):
        return

    def _send(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/v1/models":
            self._send(200, {"data": [{"id": "deepseek-chat"}]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        Handler.calls.append({"path": self.path, "body": body, "auth": self.headers.get("Authorization")})
        if Handler.fail_once and len(Handler.calls) == 1:
            self._send(429, {"error": "rate limited"})
            return
        self._send(
            200,
            {
                "choices": [{"message": {"content": json.dumps({"ok": True, "model": body.get("model")})}}],
                "usage": {"total_tokens": 10},
            },
        )


def make_settings(tmp_path: Path, port: int) -> Settings:
    config = tmp_path / "llm_providers.json"
    config.write_text(
        json.dumps(
            {
                "default_provider": "deepseek",
                "providers": {
                    "deepseek": {
                        "base_url": f"http://127.0.0.1:{port}/v1",
                        "api_key_env": "TEST_DEEPSEEK_KEY",
                        "preferred_models": ["deepseek-chat"],
                        "default_model": "deepseek-chat",
                        "timeout_seconds": 10,
                        "legacy_key": False,
                    }
                },
                "task_routes": {"answer": "deepseek"},
            }
        ),
        encoding="utf-8",
    )
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
        llm_provider="deepseek",
    )


def run_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_deepseek_openai_compatible_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_DEEPSEEK_KEY", "sk-test-deepseek")
    server = run_server()
    try:
        Handler.calls = []
        Handler.fail_once = True
        settings = make_settings(tmp_path, server.server_port)
        registry = load_llm_registry(settings)
        llm = OpenAICompatLLM(settings, registry)
        result = asyncio.run(llm.json("answer", {"question": "q"}, "只输出 JSON"))
        assert result == {"ok": True, "model": "deepseek-chat"}
        assert len(Handler.calls) == 2  # first 429, retry 200
        assert Handler.calls[-1]["path"] == "/v1/chat/completions"
        assert Handler.calls[-1]["body"]["model"] == "deepseek-chat"
        assert Handler.calls[-1]["body"]["response_format"] == {"type": "json_object"}
        assert Handler.calls[-1]["auth"] == "Bearer sk-test-deepseek"
        asyncio.run(llm.close())
    finally:
        server.shutdown()
