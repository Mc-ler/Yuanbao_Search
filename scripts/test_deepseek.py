"""Single DeepSeek API test/config entry point.

This consolidates the DeepSeek checks that used to be spread across
scripts/test_deepseek.py, probe_llm.py and fix_llm.py:

  * list /models
  * test one model (default: deepseek-flash)
  * --all-models: matrix-test every chat-capable model
  * --json: machine-readable report
  * --apply: persist the selected model to .env and config/llm_providers.json

Examples:
    ./.Search/Scripts/python.exe scripts/test_deepseek.py
    ./.Search/Scripts/python.exe scripts/test_deepseek.py --all-models
    ./.Search/Scripts/python.exe scripts/test_deepseek.py --model deepseek-v4-pro
    ./.Search/Scripts/python.exe scripts/test_deepseek.py --all-models --apply

The script never prints the key. Missing key/401/402/429/5xx produce a clear
message and a non-zero exit. No response bodies containing secrets are stored.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from claimlab.config import load_settings  # noqa: E402
from claimlab.fsutil import atomic_write_text  # noqa: E402
from claimlab.keys import bearer_auth_header, load_llm_registry  # noqa: E402

__test__ = False  # this is a CLI probe, not a pytest module

ENV_PATH = ROOT / ".env"
CONFIG_PATH = ROOT / "config" / "llm_providers.json"
NON_CHAT_MARKERS = ("embedding", "tts", "whisper", "audio", "video", "moderation", "image")


def _is_chat_model(model: str) -> bool:
    return not any(marker in model.lower() for marker in NON_CHAT_MARKERS)


def _upsert(lines: list[str], key: str, value: str) -> list[str]:
    for index, raw in enumerate(lines):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.split("=", 1)[0].strip().lower() == key.lower():
            lines[index] = f"{key}={value}"
            return lines
    lines.append(f"{key}={value}")
    return lines


def _dedupe(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for line in reversed(lines):
        stripped = line.strip()
        name = ""
        if stripped and not stripped.startswith("#") and "=" in stripped:
            name = stripped.split("=", 1)[0].strip().lower()
        if name and name in seen:
            continue
        if name:
            seen.add(name)
        result.append(line)
    result.reverse()
    return result


def apply_selection(provider: Any, model: str, working: list[str]) -> None:
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    _upsert(lines, "LLM_PROVIDER", provider.name)
    _upsert(lines, "LLM_MODEL", model)
    atomic_write_text(ENV_PATH, "\n".join(_dedupe(lines)).rstrip() + "\n")
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else {}
    raw = data.setdefault("providers", {}).setdefault(provider.name, {})
    raw["preferred_models"] = working
    raw["default_model"] = model
    atomic_write_text(CONFIG_PATH, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(f"applied LLM_PROVIDER={provider.name} LLM_MODEL={model}")
    print("restart the service to apply: ./.Search/Scripts/python.exe -m claimlab.api")


async def fetch_models(client: httpx.AsyncClient) -> list[str]:
    try:
        response = await client.get("/models")
        print(f"/models -> HTTP {response.status_code}")
        if response.status_code != 200:
            print(f"  body: {response.text[:300]}")
            return []
        data = response.json()
        models = [str(item.get("id")) for item in data.get("data", []) if isinstance(item, dict) and item.get("id")]
        print("catalog:", ", ".join(models[:50]) if models else "(empty)")
        return models
    except (httpx.HTTPError, ValueError) as exc:
        print(f"/models error: {type(exc).__name__}: {exc}")
        return []


async def probe_model(
    client: httpx.AsyncClient,
    model: str,
    *,
    use_json_mode: bool = True,
) -> dict[str, Any]:
    started = time.perf_counter()
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": "只输出 JSON，不要解释。"},
            {"role": "user", "content": '返回 {"ok": true, "service": "deepseek"}，不要其它文字。'},
        ],
        "temperature": 0,
        "max_tokens": 80,
    }
    if use_json_mode:
        body["response_format"] = {"type": "json_object"}
    record: dict[str, Any] = {"model": model, "ok": False, "status": None, "latency_ms": 0.0, "error": "", "content": ""}
    for attempt in range(3):
        try:
            response = await client.post("/chat/completions", json=body)
        except httpx.HTTPError as exc:
            record["error"] = f"transport/{type(exc).__name__}"
            if attempt < 2:
                await asyncio.sleep(0.8 * (attempt + 1))
                continue
            record["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
            return record
        if response.status_code in (400, 422) and "response_format" in body:
            body.pop("response_format", None)
            print(f"  {model}: response_format rejected; retrying without it")
            continue
        if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
            await asyncio.sleep(0.8 * (attempt + 1))
            continue
        record["status"] = response.status_code
        record["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        if response.status_code == 200:
            try:
                content = response.json()["choices"][0]["message"]["content"]
                record["content"] = str(content)[:400]
                json.loads(content)
                record["ok"] = True
            except (KeyError, IndexError, TypeError, ValueError):
                record["error"] = "invalid_json_content"
        else:
            record["error"] = f"HTTP {response.status_code}: {response.text[:240]}"
        return record
    record["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return record


async def main_async(args: argparse.Namespace) -> int:
    settings = load_settings()
    registry = load_llm_registry(settings)
    provider = registry.providers.get("deepseek")
    if provider is None:
        print("DeepSeek provider is not configured in config/llm_providers.json")
        return 2
    if not provider.key_present:
        print("DEEPSEEK_API_KEY is missing.")
        print("Run: ./.Search/Scripts/python.exe scripts/configure_keys.py llm --provider deepseek")
        print("Or put DEEPSEEK_API_KEY=sk-... in .env and restart.")
        return 2

    headers = {"Content-Type": "application/json"}
    auth = bearer_auth_header(provider.api_key)
    if auth:
        headers["Authorization"] = auth
    timeout = httpx.Timeout(max(30.0, float(args.timeout or provider.timeout_seconds or 90.0)), connect=10.0)
    async with httpx.AsyncClient(base_url=provider.base_url, headers=headers, timeout=timeout) as client:
        models = await fetch_models(client)
        configured = (settings.llm_model or "").strip()
        if configured and models and configured not in models:
            print(f"warning: .env LLM_MODEL={configured} is not in /models; the app will fall back to preferred/default.")
        candidates: list[str] = []
        if args.all_models:
            for model in [*provider.preferred_models, provider.default_model, *models]:
                if model and model not in candidates and _is_chat_model(model):
                    candidates.append(model)
        else:
            requested = args.model or provider.default_model or (models[0] if models else "")
            if requested:
                candidates = [requested]
        if not candidates:
            print("No candidate model to test.")
            return 2
        print("\nmodel tests:")
        results = []
        for model in candidates:
            result = await probe_model(client, model, use_json_mode=not args.no_json_mode)
            results.append(result)
            status = result["status"] if result["status"] is not None else "ERR"
            detail = "OK" if result["ok"] else result["error"][:140]
            print(f"  {model:28} {str(status):>4} {result['latency_ms']:7.0f}ms  {detail}")
        working = [item["model"] for item in results if item["ok"]]
        print("\nworking models:", ", ".join(working) if working else "(none)")
        if not working:
            print("Check DeepSeek key, balance, base_url, and model entitlement.")
            if args.json:
                print(json.dumps({"catalog": models, "results": results}, ensure_ascii=False, indent=2))
            return 1
        selected = args.model if args.model in working else working[0]
        print(f"selected: {selected}")
        if args.apply:
            apply_selection(provider, selected, working)
        else:
            print("verification only; use --apply to persist LLM_MODEL and config preferred_models")
        if args.json:
            print(json.dumps({"catalog": models, "results": results, "selected": selected}, ensure_ascii=False, indent=2))
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Test and configure the DeepSeek API")
    parser.add_argument("--model", default="", help="test this model (default: provider default)")
    parser.add_argument("--all-models", action="store_true", help="matrix-test all chat-capable catalog models")
    parser.add_argument("--no-json-mode", action="store_true", help="do not send response_format")
    parser.add_argument("--apply", action="store_true", help="persist the selected model to .env/config")
    parser.add_argument("--json", action="store_true", help="print a machine-readable report")
    parser.add_argument("--timeout", type=float, default=0, help="request timeout seconds (default: provider setting)")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
