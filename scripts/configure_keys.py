"""Configure Yuanbao and third-party LLM keys in the local .env.

Examples:
    ./.Search/Scripts/python.exe scripts/configure_keys.py show
    ./.Search/Scripts/python.exe scripts/configure_keys.py yuanbao
    ./.Search/Scripts/python.exe scripts/configure_keys.py llm --provider toklens
    ./.Search/Scripts/python.exe scripts/configure_keys.py llm --provider gpt --model gpt-4o-mini

Secrets are read with getpass by default and never printed. The Yuanbao key is
stored raw; the application builds a single Bearer header at request time.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from claimlab.config import load_settings  # noqa: E402
from claimlab.fsutil import atomic_write_text  # noqa: E402
from claimlab.keys import (  # noqa: E402
    bearer_auth_header,
    key_info,
    load_llm_registry,
    normalize_base_url,
    select_llm,
    strip_bearer,
)

ENV_PATH = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"
PROVIDER_PREFIX = {"gpt": "GPT", "codex": "CODEX", "deepseek": "DEEPSEEK"}


def read_env_lines() -> list[str]:
    source = ENV_PATH if ENV_PATH.exists() else ENV_EXAMPLE
    if not source.exists():
        return []
    return source.read_text(encoding="utf-8").splitlines()


def upsert(lines: list[str], key: str, value: str) -> list[str]:
    lowered = key.lower()
    for index, raw in enumerate(lines):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name = stripped.split("=", 1)[0].strip()
        if name.lower() == lowered:
            lines[index] = f"{key}={value}"
            return lines
    lines.append(f"{key}={value}")
    return lines


def write_env(lines: list[str]) -> None:
    atomic_write_text(ENV_PATH, "\n".join(lines).rstrip() + "\n")


def prompt_secret(label: str, provided: str | None) -> str:
    if provided is not None:
        return provided.strip()
    return getpass.getpass(label).strip()


def provider_defaults() -> dict:
    config_path = ROOT / "config" / "llm_providers.json"
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def cmd_show(args: argparse.Namespace) -> int:
    settings = load_settings()
    registry = load_llm_registry(settings)
    info = key_info(settings.search_api_key)
    host = ""
    try:
        host = urlsplit(settings.search_base_url).hostname or ""
    except ValueError:
        pass
    print("Yuanbao Search")
    print(f"  base_url={settings.search_base_url} host={host}")
    print(
        f"  key_present={info['present']} length={info['length']} "
        f"had_bearer_prefix={info['had_bearer_prefix']}"
    )
    print("  auth header will be: " + ("Bearer <key>" if info["present"] else "(missing)"))
    print("\nLLM providers")
    for provider in registry.providers.values():
        print(
            f"  {provider.name}: key_present={provider.key_present} base_url={provider.base_url} "
            f"preferred={provider.preferred_models} default={provider.default_model or '-'}"
        )
    if registry.has_any_key:
        try:
            selection = select_llm(settings, registry, "extract_claims")
            print(f"  selected for extract_claims: provider={selection.provider.name} model={selection.model}")
        except Exception as exc:
            print(f"  selection error: {exc}")
    else:
        print("  no LLM key set; set GPT_API_KEY / CODEX_API_KEY / TOKLENS_API_KEY (or LLM_API_KEY)")
    if args.check_network:
        print("\nNetwork checks are performed by scripts/probe_llm.py and scripts/probe_search.py.")
    return 0


def cmd_yuanbao(args: argparse.Namespace) -> int:
    key = prompt_secret("Yuanbao Search API key (input hidden): ", args.key)
    if not key:
        print("empty key; nothing written")
        return 2
    info = key_info(key)
    raw = strip_bearer(key)
    lines = read_env_lines()
    upsert(lines, "SEARCH_API_KEY", raw)
    if args.base_url:
        upsert(lines, "SEARCH_BASE_URL", args.base_url.rstrip("/"))
    write_env(lines)
    print(f"stored SEARCH_API_KEY raw (length={len(raw)}) in {ENV_PATH}")
    if info["had_bearer_prefix"]:
        print("removed the configured Bearer prefix; the app adds it at request time.")
    print("restart the service to apply: ./.Search/Scripts/python.exe -m claimlab.api")
    return 0


def cmd_llm(args: argparse.Namespace) -> int:
    config = provider_defaults()
    providers = config.get("providers") if isinstance(config, dict) else {}
    provider = args.provider
    if provider not in {"gpt", "codex", "deepseek", "toklens"}:
        print("provider must be gpt, codex, deepseek, or toklens")
        return 2
    default_base = "https://api.deepseek.com/v1" if provider == "deepseek" else "https://lax.toklens.ai/v1"
    if provider in {"gpt", "codex", "deepseek"} and isinstance(providers, dict):
        raw_provider = providers.get(provider) or {}
        default_base = str(raw_provider.get("base_url") or default_base)
    base_url = normalize_base_url(args.base_url or default_base)
    key = prompt_secret(f"{provider} API key (input hidden): ", args.key)
    if not key:
        print("empty key; nothing written")
        return 2
    raw = strip_bearer(key)
    lines = read_env_lines()
    if provider == "toklens":
        upsert(lines, "TOKLENS_API_KEY", raw)
        upsert(lines, "LLM_PROVIDER", "gpt")
        print(f"stored TOKLENS_API_KEY raw (length={len(raw)}); gpt/codex providers share it")
    else:
        prefix = PROVIDER_PREFIX[provider]
        upsert(lines, f"{prefix}_BASE_URL", base_url)
        upsert(lines, f"{prefix}_API_KEY", raw)
        upsert(lines, "LLM_PROVIDER", provider)
        print(f"stored {prefix}_API_KEY raw (length={len(raw)}) and {prefix}_BASE_URL={base_url}")
    if args.model:
        upsert(lines, "LLM_MODEL", args.model.strip())
        print(f"LLM_MODEL={args.model.strip()} (explicit override)")
    else:
        print("LLM_MODEL left empty; the client will choose from preferred models + /models")
    write_env(lines)
    print(f"saved to {ENV_PATH}; restart the service to apply.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure Yuanbao Search and third-party LLM keys")
    sub = parser.add_subparsers(dest="command", required=True)

    show = sub.add_parser("show", help="show key presence and provider selection (no secrets)")
    show.add_argument("--check-network", action="store_true", help="hint for the probe scripts")
    show.set_defaults(func=cmd_show)

    yuanbao = sub.add_parser("yuanbao", help="write the raw Yuanbao Search key")
    yuanbao.add_argument("--key", help="optional non-interactive key (avoid shell history)")
    yuanbao.add_argument("--base-url", help="optional SearchPro base URL")
    yuanbao.set_defaults(func=cmd_yuanbao)

    llm = sub.add_parser("llm", help="write a third-party LLM key")
    llm.add_argument("--provider", default="deepseek", choices=["deepseek", "gpt", "codex", "toklens"])
    llm.add_argument("--key", help="optional non-interactive key (avoid shell history)")
    llm.add_argument("--base-url", help="provider base URL (default: DeepSeek /v1)")
    llm.add_argument("--model", help="optional explicit model; empty means auto-select")
    llm.set_defaults(func=cmd_llm)

    args = parser.parse_args()
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
