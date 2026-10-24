"""Diagnose Toklens model/group mismatches and select a working model.

The key can be valid while the key's group has no account for a model name.
``/models`` is a catalog, not an entitlement check: a model can appear there and
still return ``model_not_found`` on ``/chat/completions``. This script tests each
chat-capable model with a minimal request, then prints (and optionally applies)
the exact .env and config values.

    python scripts/probe_llm.py
    python scripts/probe_llm.py --provider gpt --apply
    python scripts/probe_llm.py --model gpt-5.5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from claimlab.config import ROOT as PROJECT_ROOT, load_settings  # noqa: E402
from claimlab.fsutil import atomic_write_text  # noqa: E402
from claimlab.keys import bearer_auth_header, load_llm_registry  # noqa: E402

NON_CHAT_MARKERS = ("image", "embedding", "tts", "whisper", "audio", "video", "moderation")
MODEL_PRIORITY = {
    "gpt": [
        "gpt-5.6-sol",
        "gpt-5.6-luna",
        "gpt-6.1-sol",
        "gpt-6-sol",
        "gpt-6-luna",
        "gpt-5.5",
    ],
    "codex": ["codex-auto-review", "gpt-5.6-sol", "gpt-6.1-sol"],
}
ENV_PATH = PROJECT_ROOT / ".env"
CONFIG_PATH = PROJECT_ROOT / "config" / "llm_providers.json"



def read_env_lines() -> list[str]:
    return ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []


def upsert(lines: list[str], key: str, value: str) -> list[str]:
    for index, raw in enumerate(lines):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.split("=", 1)[0].strip().lower() == key.lower():
            lines[index] = f"{key}={value}"
            return lines
    lines.append(f"{key}={value}")
    return lines


def is_chat_candidate(model: str) -> bool:
    lowered = model.lower()
    return not any(marker in lowered for marker in NON_CHAT_MARKERS)


async def fetch_models(client: httpx.AsyncClient) -> list[str]:
    response = await client.get("/models")
    print(f"/models -> HTTP {response.status_code}")
    if response.status_code != 200:
        print(f"  body: {response.text[:300]}")
        return []
    data = response.json()
    models = [
        str(item.get("id"))
        for item in data.get("data", [])
        if isinstance(item, dict) and item.get("id")
    ]
    print("catalog:", ", ".join(models[:40]) if models else "(empty)")
    return models


async def test_model(client: httpx.AsyncClient, model: str) -> dict[str, Any]:
    started = time.perf_counter()
    record: dict[str, Any] = {"model": model, "ok": False, "status": None, "error": "", "latency_ms": 0.0}
    try:
        response = await client.post(
            "/chat/completions",
            json={
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": 'Return exactly this JSON and nothing else: {"ok": true}',
                    }
                ],
            },
        )
        record["status"] = response.status_code
        record["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        record["ok"] = response.status_code == 200
        if response.status_code == 200:
            try:
                record["content"] = response.json()["choices"][0]["message"]["content"][:200]
            except (KeyError, IndexError, TypeError, ValueError):
                record["content"] = response.text[:200]
        else:
            try:
                error = response.json().get("error") or {}
                record["error"] = f"{error.get('type', '')}: {error.get('message', '')}".strip(": ")
            except ValueError:
                record["error"] = response.text[:300]
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
        record["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return record


def recommendation(provider: Any, working: list[str], selected: str) -> dict[str, Any]:
    return {
        "env": {
            "LLM_PROVIDER": provider.name,
            "LLM_MODEL": selected,
            "LLM_BASE_URL": provider.base_url,
        },
        "config": {
            "provider": provider.name,
            "preferred_models": working,
            "default_model": selected,
        },
    }


def order_working(provider: Any, working: list[str]) -> list[str]:
    priority = MODEL_PRIORITY.get(provider.name, [])
    ordered = [model for model in priority if model in working]
    ordered.extend(model for model in working if model not in ordered)
    return ordered


def apply_fix(provider: Any, working: list[str], selected: str, config_only: bool = False) -> None:
    if not config_only:
        lines = read_env_lines()
        upsert(lines, "LLM_PROVIDER", provider.name)
        upsert(lines, "LLM_MODEL", selected)
        atomic_write_text(ENV_PATH, "\n".join(lines).rstrip() + "\n")
        print(f"updated .env: LLM_PROVIDER={provider.name} LLM_MODEL={selected}")

    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else {}
    providers = data.setdefault("providers", {})
    raw = providers.setdefault(provider.name, {})
    raw["preferred_models"] = working
    raw["default_model"] = selected
    atomic_write_text(CONFIG_PATH, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(f"updated config/llm_providers.json: providers.{provider.name}.preferred_models={working}")


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="Diagnose and fix the Toklens model/group mismatch")
    parser.add_argument("--provider", help="provider name (default: configured default)")
    parser.add_argument("--model", help="test this model first / select it if it works")
    parser.add_argument("--apply", action="store_true", help="write the working model to .env and config")
    parser.add_argument("--config-only", action="store_true", help="with --apply, update config but not .env")
    parser.add_argument("--json", action="store_true", help="print the matrix report as JSON")
    args = parser.parse_args()

    settings = load_settings()
    registry = load_llm_registry(settings)
    provider = registry.provider_for("probe", args.provider or settings.llm_provider or None)
    if provider is None or not provider.key_present:
        print("No LLM key configured. Set GPT_API_KEY / CODEX_API_KEY / TOKLENS_API_KEY (or LLM_API_KEY).")
        return 2

    print(f"provider: {provider.name}")
    print(f"base_url: {provider.base_url}")
    print(f"key_present: {provider.key_present} key_length: {len(provider.api_key)}")
    print(f"configured LLM_MODEL: {settings.llm_model or '(empty)'}")
    print(f"preferred_models: {provider.preferred_models}")
    print(f"default_model: {provider.default_model or '-'}")

    headers = {"Authorization": bearer_auth_header(provider.api_key)}
    async with httpx.AsyncClient(base_url=provider.base_url, headers=headers, timeout=40.0) as client:
        catalog = await fetch_models(client)
        if not catalog:
            print("\nCould not read /models; check base_url and key permission.")
            return 2

        candidates: list[str] = []
        explicit = [item for item in [args.model, settings.llm_model] if item]
        for model in [*explicit, *provider.preferred_models, provider.default_model, *catalog]:
            if model and model not in candidates:
                candidates.append(model)
        # Keep an explicitly requested model even if its name looks non-chat;
        # otherwise only test plausible chat models.
        candidates = [model for model in candidates if model in explicit or is_chat_candidate(model)]

        print("\nmodel matrix (minimal chat request, no response_format):")
        results: list[dict[str, Any]] = []
        for model in candidates:
            result = await test_model(client, model)
            results.append(result)
            status = result["status"] if result["status"] is not None else "ERR"
            detail = "OK" if result["ok"] else result["error"][:120]
            print(f"  {model:28} {str(status):>4}  {detail}")

        working = [result["model"] for result in results if result["ok"]]
        working = order_working(provider, working)
        print("\nworking models:", ", ".join(working) if working else "(none)")

        if not working:
            print(
                "\nROOT CAUSE: the key's Toklens group has no configured account that supports "
                "any tested chat model. /models is a catalog, not an entitlement list."
            )
            print("FIX: in the Toklens console, add/authorize a chat-capable account to this group,")
            print("or create the key in a group whose account supports the model. Then rerun this script.")
            print("Do not set LLM_MODEL=gpt-4.1; it is not in this group's supported catalog.")
            if args.json:
                print(
                    json.dumps(
                        {"provider": provider.name, "catalog": catalog, "results": results},
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            return 2

        selected = next((model for model in [args.model, settings.llm_model] if model in working), working[0])
        rec = recommendation(provider, working, selected)
        print("\nrecommended values:")
        print(f"  .env: LLM_PROVIDER={rec['env']['LLM_PROVIDER']}")
        print(f"  .env: LLM_MODEL={rec['env']['LLM_MODEL']}")
        print(f"  .env: LLM_BASE_URL={rec['env']['LLM_BASE_URL']}")
        print(
            "  config/llm_providers.json: "
            f"providers.{provider.name}.preferred_models={json.dumps(rec['config']['preferred_models'], ensure_ascii=False)}"
        )
        print(f"  config/llm_providers.json: providers.{provider.name}.default_model={selected}")

        if args.apply:
            apply_fix(provider, working, selected, config_only=args.config_only)
            print("restart the service to reload .env, then rerun the probe.")
        else:
            print("rerun with --apply to write these values, or edit .env/config manually.")

        # Verify the exact path the application uses, not only the raw endpoint.
        os.environ["LLM_MODEL"] = selected
        os.environ["LLM_PROVIDER"] = provider.name
        from claimlab.config import load_settings as reload_settings
        from claimlab.keys import load_llm_registry as reload_registry
        from claimlab.llm.client import OpenAICompatLLM

        probe_settings = reload_settings()
        probe_registry = reload_registry(probe_settings)
        llm = OpenAICompatLLM(probe_settings, probe_registry)
        try:
            result = await llm.json(
                "probe",
                {"ping": "pong"},
                '只输出 JSON：{"ok": true, "model": "..."}',
            )
            print("app-path json probe:", json.dumps(result, ensure_ascii=False))
        finally:
            await llm.close()

        if args.json:
            print(
                json.dumps(
                    {"provider": provider.name, "catalog": catalog, "results": results, "recommendation": rec},
                    ensure_ascii=False,
                    indent=2,
                )
            )
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async()))
