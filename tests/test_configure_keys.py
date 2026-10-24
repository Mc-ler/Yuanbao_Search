import io
from pathlib import Path

from scripts import configure_keys


def test_prompt_secret_non_tty_reads_line(monkeypatch):
    monkeypatch.setattr(configure_keys.sys, "stdin", io.StringIO("sk-test\n"))
    assert configure_keys.prompt_secret("key: ", None) == "sk-test"


def test_write_env_dedupes_keep_last(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    monkeypatch.setattr(configure_keys, "ENV_PATH", env)
    configure_keys.write_env(
        ["A=1", "B=2", "A=3", "# comment", "LLM_PROVIDER=gpt", "LLM_PROVIDER=deepseek"]
    )
    text = env.read_text(encoding="utf-8")
    assert text.count("A=") == 1
    assert "A=3" in text
    assert text.count("LLM_PROVIDER=") == 1
    assert "LLM_PROVIDER=deepseek" in text
    assert "# comment" in text
