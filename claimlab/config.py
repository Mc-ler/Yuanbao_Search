"""Configuration and filesystem layout for claimlab.

The project deliberately avoids python-dotenv: one small parser keeps the
deployment surface small and makes the offline/demo path predictable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
FIXTURES_DIR = ROOT / "fixtures"
CACHE_DIR = ROOT / "cache"
ARCHIVE_DIR = ROOT / "archive"
STATE_DIR = ROOT / "state"
WEB_DIR = ROOT / "web"
LOGS_DIR = ROOT / "logs"
DELIVERABLES_DIR = ROOT / "deliverables"


def load_env_file(path: Path | None = None) -> None:
    """Load KEY=VALUE lines without overriding already-set environment vars."""
    env_path = path or (ROOT / ".env")
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _env_str(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    search_provider: str = "api"  # api | fake
    search_api_key: str = ""
    search_base_url: str = "https://api.wsa.cloud.tencent.com"

    llm_base_url: str = "https://lax.toklens.ai/v1"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_provider: str = ""
    llm_providers_path: Path = CONFIG_DIR / "llm_providers.json"

    app_host: str = "127.0.0.1"
    app_port: int = 8000
    app_api_token: str = ""

    max_calls_per_assertion: int = 8
    max_calls_per_run: int = 56
    max_calls_per_day: int = 800
    max_agent_steps: int = 12
    run_wall_seconds: int = 90
    dedup_threshold: float = 0.65
    cache_ttl_hours: float = 72.0
    offline: bool = False
    log_level: str = "INFO"
    log_max_bytes: int = 5_000_000
    log_backup_count: int = 5

    root: Path = ROOT
    cache_dir: Path = CACHE_DIR
    archive_dir: Path = ARCHIVE_DIR
    state_dir: Path = STATE_DIR
    config_dir: Path = CONFIG_DIR
    fixtures_dir: Path = FIXTURES_DIR
    web_dir: Path = WEB_DIR
    logs_dir: Path = LOGS_DIR

    @property
    def search_key_present(self) -> bool:
        return bool(self.search_api_key)

    @property
    def llm_key_present(self) -> bool:
        if self.llm_api_key:
            return True
        return any(
            os.environ.get(name)
            for name in ("LLM_API_KEY", "GPT_API_KEY", "CODEX_API_KEY", "TOKLENS_API_KEY")
        )

    @property
    def demo_mode(self) -> bool:
        return not self.search_key_present

    def ensure_dirs(self) -> None:
        for path in (self.cache_dir, self.archive_dir, self.state_dir, self.logs_dir, DELIVERABLES_DIR):
            path.mkdir(parents=True, exist_ok=True)

    def public_dict(self) -> dict:
        """Health-safe view: booleans, never secret values."""
        return {
            "search_provider": self.search_provider,
            "search_base_url": self.search_base_url,
            "search_endpoint": "/SearchPro",
            "search_key_present": self.search_key_present,
            "llm_key_present": self.llm_key_present,
            "llm_model": self.llm_model or None,
            "llm_provider": self.llm_provider or None,
            "offline": self.offline,
            "demo_mode": self.demo_mode,
            "budgets": {
                "per_assertion": self.max_calls_per_assertion,
                "per_run": self.max_calls_per_run,
                "per_day": self.max_calls_per_day,
                "agent_steps": self.max_agent_steps,
                "wall_seconds": self.run_wall_seconds,
            },
            "dedup_threshold": self.dedup_threshold,
        }


def load_settings(env_file: Path | None = None) -> Settings:
    load_env_file(env_file)
    llm_base = _env_str("LLM_BASE_URL", "https://lax.toklens.ai/v1").rstrip("/")
    if llm_base in {"https://lax.toklens.ai", "http://lax.toklens.ai"}:
        llm_base += "/v1"
    settings = Settings(
        search_provider=_env_str("SEARCH_PROVIDER", "api").lower() or "api",
        search_api_key=_env_str("SEARCH_API_KEY"),
        search_base_url=_env_str("SEARCH_BASE_URL", "https://api.wsa.cloud.tencent.com").rstrip("/"),
        llm_base_url=llm_base,
        llm_api_key=_env_str("LLM_API_KEY"),
        llm_model=_env_str("LLM_MODEL"),
        llm_provider=_env_str("LLM_PROVIDER"),
        app_host=_env_str("APP_HOST", "127.0.0.1"),
        app_port=_env_int("APP_PORT", 8000),
        app_api_token=_env_str("APP_API_TOKEN"),
        max_calls_per_assertion=_env_int("MAX_CALLS_PER_ASSERTION", 8),
        max_calls_per_run=_env_int("MAX_CALLS_PER_RUN", 56),
        max_calls_per_day=_env_int("MAX_CALLS_PER_DAY", 800),
        max_agent_steps=_env_int("MAX_AGENT_STEPS", 12),
        run_wall_seconds=_env_int("RUN_WALL_SECONDS", 90),
        dedup_threshold=_env_float("DEDUP_THRESHOLD", 0.65),
        cache_ttl_hours=_env_float("CACHE_TTL_HOURS", 72.0),
        offline=_env_bool("OFFLINE", False),
        log_level=_env_str("LOG_LEVEL", "INFO").upper(),
        log_max_bytes=_env_int("LOG_MAX_BYTES", 5_000_000),
        log_backup_count=_env_int("LOG_BACKUP_COUNT", 5),
    )
    if settings.search_provider not in {"api", "fake"}:
        settings.search_provider = "api"
    settings.ensure_dirs()
    return settings
