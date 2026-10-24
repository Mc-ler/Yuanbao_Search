"""Verify one exact GPT/Codex model; --apply persists on success.

For DeepSeek use scripts/test_deepseek.py (single entry point with --all-models
and --apply). This script is kept for Toklens GPT/Codex diagnostics.


/models is a catalog, not an entitlement check. This script bypasses the app's
cache and fallback selection. No keys are printed or backed up. Restart the
service after applying and clear conflicting inherited environment overrides.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from claimlab.config import ROOT as PROJECT_ROOT, load_settings  # noqa: E402
from claimlab.keys import bearer_auth_header, load_llm_registry  # noqa: E402

ENV_PATH = PROJECT_ROOT / ".env"
CONFIG_PATH = PROJECT_ROOT / "config" / "llm_providers.json"
DEFAULT_MODEL = "gpt-6-astra"
DEFAULT_PROVIDER = "gpt"


def _error_type(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return "non_json_error"
    error = data.get("error") if isinstance(data, dict) else None
    allowed = {"model_not_found", "invalid_request_error", "authentication_error",
               "permission_error", "rate_limit_error", "server_error", "unsupported_parameter"}
    if isinstance(error, dict):
        for key in ("code", "type"):
            value = error.get(key)
            if isinstance(value, str) and value in allowed:
                return value
    return "unknown_error"


def _response_format_unsupported(response: httpx.Response) -> bool:
    if response.status_code not in (400, 422):
        return False
    try:
        data = response.json()
    except ValueError:
        return False
    error = data.get("error") if isinstance(data, dict) else None
    if not isinstance(error, dict):
        return False
    if error.get("code") == "model_not_found" or error.get("type") == "model_not_found":
        return False
    message = str(error.get("message", "")).lower()
    param = error.get("param")
    targeted = param == "response_format" or (param is None and "response_format" in message)
    unsupported = error.get("code") in {"unsupported_parameter", "unknown_parameter"} or any(
        word in message for word in ("unsupported", "not supported", "does not support", "unknown parameter", "unrecognized parameter")
    )
    return targeted and unsupported


def _json_ok(response: httpx.Response) -> bool:
    try:
        content = response.json()["choices"][0]["message"]["content"]
        parsed = json.loads(content)  # strict JSON; no fenced/explanatory text
        return isinstance(parsed, dict) and parsed.get("ok") is True
    except (ValueError, TypeError, KeyError, IndexError):
        return False


def verify_model(client: httpx.Client, model: str) -> tuple[bool, str]:
    """Fresh direct request: no app cache, model fallback, or automatic retry."""
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content":
            'Return exactly this JSON and nothing else: {"ok": true}. '
            f"Ignore this unique verification ID: {uuid.uuid4().hex}"}],
        "response_format": {"type": "json_object"},
    }
    try:
        response = client.post("chat/completions", json=body)
        if _response_format_unsupported(response):
            body = {key: value for key, value in body.items() if key != "response_format"}
            response = client.post("chat/completions", json=body)
    except httpx.HTTPError as exc:
        return False, f"transport/{type(exc).__name__}"
    if response.status_code != 200:
        return False, f"HTTP {response.status_code}/{_error_type(response)}"
    return (True, "HTTP 200/json_ok_true") if _json_ok(response) else (False, "HTTP 200/invalid_json_ok")


def catalog_has_exact_model(client: httpx.Client, model: str) -> tuple[bool, str]:
    try:
        response = client.get("models")
    except httpx.HTTPError as exc:
        return False, f"transport/{type(exc).__name__}"
    if response.status_code != 200:
        return False, f"HTTP {response.status_code}/{_error_type(response)}"
    try:
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            return False, "HTTP 200/invalid_catalog"
        found = any(isinstance(item, dict) and item.get("id") == model for item in data["data"])
    except (ValueError, TypeError, AttributeError):
        return False, "HTTP 200/invalid_catalog"
    return (True, "HTTP 200/exact_model_present") if found else (False, "HTTP 200/model_not_in_catalog")


def _env_text(text: str, provider: str, model: str) -> str:
    """Preserve all unrelated bytes/newlines and update every exact duplicate."""
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    for key, value in (("LLM_PROVIDER", provider), ("LLM_MODEL", model)):
        found = False
        for index, line in enumerate(lines):
            match = re.match(r"^(\s*" + key + r"\s*=)[^\r\n]*(\r?\n)?$", line)
            if match:
                lines[index] = match[1] + value + (match[2] or "")
                found = True
        if not found:
            if lines and not lines[-1].endswith(("\n", "\r")):
                lines[-1] += newline
            lines.append(f"{key}={value}{newline}")
    return "".join(lines)


def persist(provider_name: str, model: str, provider_preferred: list[str], *,
            env_path: Path = ENV_PATH, config_path: Path = CONFIG_PATH) -> None:
    """Prevalidate both files; write in place without secret backup/temp files.

    Two files cannot be atomically committed together. On an I/O failure attempt
    an in-memory rollback, then report only a safe error type to the caller.
    """
    env_existed = env_path.exists()
    old_env = env_path.read_bytes() if env_existed else b""
    old_config = config_path.read_bytes()
    data = json.loads(old_config.decode("utf-8"))
    provider = data["providers"][provider_name]
    provider["preferred_models"] = list(dict.fromkeys([model, *provider_preferred]))
    provider["default_model"] = model
    new_config = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    new_env = _env_text(old_env.decode("utf-8"), provider_name, model).encode("utf-8")
    try:
        config_path.write_bytes(new_config)
        env_path.write_bytes(new_env)
    except OSError:
        try:
            config_path.write_bytes(old_config)
            if env_existed:
                env_path.write_bytes(old_env)
            elif env_path.exists():
                env_path.unlink()
        except OSError:
            print("warning: rollback failed; inspect both configuration files locally")
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify one exact Toklens model; no speculative fallback")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--provider", default=DEFAULT_PROVIDER)
    parser.add_argument("--apply", action="store_true", help="persist only after a fresh successful JSON chat")
    args = parser.parse_args(argv)
    if not all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*", value) for value in (args.model, args.provider)):
        print("error: invalid model/provider identifier")
        return 2
    inherited = [key for key in ("LLM_PROVIDER", "LLM_MODEL") if key in os.environ]
    if inherited:
        print("warning: inherited environment overrides .env: " + ", ".join(inherited))
    try:
        settings = load_settings()
        registry = load_llm_registry(settings)
        provider = registry.providers.get(args.provider)  # never registry fallback
        if provider is None or not provider.key_present:
            print("error: selected provider is missing or has no configured key")
            return 2
        headers = httpx.Headers(provider.headers)
        headers["Authorization"] = bearer_auth_header(provider.api_key)
        headers["Cache-Control"] = "no-cache, no-store"
        with httpx.Client(base_url=provider.base_url.rstrip("/") + "/", headers=headers,
                          timeout=40.0, follow_redirects=False) as client:
            catalog_ok, detail = catalog_has_exact_model(client, args.model)
            print(f"catalog {args.model}: {detail}")
            if not catalog_ok:
                return 2
            chat_ok, detail = verify_model(client, args.model)
            print(f"direct chat {args.model}: {detail}")
            if not chat_ok:
                print("Catalog presence does not prove group access; check Toklens model/group authorization.")
                return 2
        if args.apply:
            persist(args.provider, args.model, provider.preferred_models,
                    env_path=ENV_PATH, config_path=CONFIG_PATH)
            print(f"applied LLM_PROVIDER={args.provider} LLM_MODEL={args.model}; restart the service")
        else:
            print("verification only; rerun with --apply to persist")
        return 0
    except Exception as exc:
        # Do not leak keys, URLs, response bodies, dataclasses or exception messages.
        print(f"error: {type(exc).__name__}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
