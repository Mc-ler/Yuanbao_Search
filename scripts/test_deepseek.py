"""Verify a real DeepSeek API call end to end (no app pipeline).

Usage:
    ./.Search/Scripts/python.exe scripts/test_deepseek.py
    ./.Search/Scripts/python.exe scripts/test_deepseek.py --model deepseek-chat

It reads DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL from .env, optionally lists
/models, then makes a tiny JSON-mode chat request with retries and prints the
result. Missing key or auth failure exits non-zero with a clear message.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from claimlab.config import load_settings  # noqa: E402
from claimlab.keys import bearer_auth_header, load_llm_registry  # noqa: E402


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
    timeout = httpx.Timeout(max(30.0, float(provider.timeout_seconds or 90.0)), connect=10.0)
    async with httpx.AsyncClient(base_url=provider.base_url, headers=headers, timeout=timeout) as client:
        models: list[str] = []
        try:
            response = await client.get("/models")
            if response.status_code == 200:
                models = [str(item.get("id")) for item in response.json().get("data", []) if item.get("id")]
                print("models:", ", ".join(models) or "(empty)")
            else:
                print(f"/models -> HTTP {response.status_code}: {response.text[:180]}")
        except httpx.HTTPError as exc:
            print(f"/models transport: {type(exc).__name__}: {exc}")
        model = args.model or ("deepseek-chat" if "deepseek-chat" in models or not models else models[0])
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": "只输出 JSON，不要解释。"},
                {"role": "user", "content": "返回 {\"ok\": true, \"service\": \"deepseek\"}，不要其它文字。"},
            ],
            "temperature": 0,
            "max_tokens": 80,
            "response_format": {"type": "json_object"},
        }
        last_error = ""
        started = time.perf_counter()
        for attempt in range(3):
            try:
                response = await client.post("/chat/completions", json=body)
            except httpx.HTTPError as exc:
                last_error = f"transport: {type(exc).__name__}"
                if attempt < 2:
                    await asyncio.sleep(0.8 * (attempt + 1))
                    continue
                print("FAILED:", last_error)
                return 1
            if response.status_code in (400, 422) and "response_format" in body:
                body.pop("response_format", None)
                print("JSON mode rejected; retrying without response_format")
                continue
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                await asyncio.sleep(0.8 * (attempt + 1))
                continue
            latency = (time.perf_counter() - started) * 1000
            if response.status_code >= 400:
                print(f"FAILED: HTTP {response.status_code}: {response.text[:400]}")
                return 1
            data = response.json()
            try:
                content = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                print("FAILED: unexpected response shape")
                return 1
            print(f"OK model={model} latency={latency:.0f}ms")
            print("content:", content[:500])
            print("usage:", data.get("usage"))
            return 0
        print("FAILED:", last_error or "request failed")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Test a real DeepSeek API call")
    parser.add_argument("--model", default="", help="override model (default: deepseek-chat)")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
