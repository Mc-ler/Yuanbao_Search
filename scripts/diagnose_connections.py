"""End-to-end connection / configuration diagnostics for claimlab.

Read-only: never writes .env, never changes server state. It answers three
questions the UI cannot:

1. Does the process behind a local port actually run with the .env we think?
2. Is the configured LLM endpoint/key able to produce a strict JSON answer?
3. Does SearchPro accept the parameters the planner sends (Site/Industry/
   Freshness), and which Site spellings silently return zero pages?

Examples (Windows PowerShell):
    ./.Search/Scripts/python.exe scripts/diagnose_connections.py
    ./.Search/Scripts/python.exe scripts/diagnose_connections.py --base-url http://127.0.0.1:8010
    ./.Search/Scripts/python.exe scripts/diagnose_connections.py --plan
    ./.Search/Scripts/python.exe scripts/diagnose_connections.py --skip-live

Exit code 0 = no FAIL, 1 = at least one FAIL.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from claimlab.config import load_settings  # noqa: E402
from claimlab.contracts import SearchRequest  # noqa: E402
from claimlab.keys import bearer_auth_header, key_info, load_llm_registry  # noqa: E402
from claimlab.llm.client import _extract_json  # noqa: E402
from claimlab.search.normalize import normalize_api_response  # noqa: E402

WIDTH = 34


def line(label: str, value: Any) -> None:
    print(f"  {label:<{WIDTH}}{value}")


def parse_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        text = raw.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def env_overrides(dotenv: dict[str, str]) -> list[tuple[str, str, str]]:
    """Keys where the current process env differs from .env."""
    result: list[tuple[str, str, str]] = []
    for key, from_file in dotenv.items():
        current = (os.environ.get(key) or "").strip()
        if current and current != from_file:
            result.append((key, from_file, current))
    return result


async def async_main() -> tuple[dict[str, Any], list[tuple[str, str, str]]]:
    findings: list[tuple[str, str, str]] = []  # (level, title, detail)

    def add(level: str, title: str, detail: str) -> None:
        findings.append((level, title, detail))

    settings = load_settings()
    dotenv = parse_dotenv(settings.root / ".env")
    overrides = env_overrides(dotenv)

    print("=" * 78)
    print("claimlab connection diagnostics")
    print("=" * 78)
    print("\n[1] .env vs this process")
    line("SEARCH_PROVIDER", settings.search_provider)
    line("SEARCH_BASE_URL", settings.search_base_url)
    line("SEARCH_API_KEY", key_info(settings.search_api_key))
    line("LLM_PROVIDER", settings.llm_provider or "(registry default)")
    line("LLM_MODEL", settings.llm_model or "(provider default)")
    line("LLM key present", settings.llm_key_present)
    if overrides:
        add(
            "WARN",
            "进程环境覆盖 .env",
            "；".join(f"{key}={current[:40]} (文件值 {from_file[:40]})" for key, from_file, current in overrides),
        )
        for key, from_file, current in overrides:
            print(f"  ! {key}: process={current[:60]!r} file={from_file[:60]!r}")
    else:
        print("  (no process env overrides detected for keys present in .env)")

    registry = load_llm_registry(settings)
    deepseek = registry.providers.get("deepseek")
    gpt = registry.providers.get("gpt")
    print("\n[2] LLM providers (resolved)")
    for provider in registry.providers.values():
        line(
            f"{provider.name}",
            f"base={provider.base_url} key_len={len(provider.api_key)} vision={provider.vision}",
        )

    # ---- service health -------------------------------------------------
    server_llm_base = ""
    if args.base_url:
        print(f"\n[3] /api/health at {args.base_url}")
        try:
            async with httpx.AsyncClient(base_url=args.base_url, timeout=30.0) as client:
                resp = await client.get("/api/health")
            if resp.status_code != 200:
                add("FAIL", "健康接口不可用", f"HTTP {resp.status_code}: {resp.text[:160]}")
                line("HTTP", resp.status_code)
            else:
                health = resp.json()
                provided = next(
                    (item for item in (health.get("llm", {}).get("providers") or []) if item.get("name") == "deepseek"),
                    {},
                )
                line("search_ready", health.get("search_ready"))
                line("llm_ready", health.get("llm_ready"))
                line("llm.provider", (health.get("llm") or {}).get("provider"))
                line("llm.model", (health.get("llm") or {}).get("model"))
                line("settings.llm_model", (health.get("settings") or {}).get("llm_model"))
                line("deepseek.base_url", provided.get("base_url"))
                server_llm_base = str(provided.get("base_url") or "").rstrip("/")
                line("search provider", (health.get("settings") or {}).get("search_provider"))
                if not health.get("search_ready"):
                    add("FAIL", "Search 未就绪", "检查 SEARCH_API_KEY")
                if not health.get("llm_ready"):
                    add("WARN", "LLM 未就绪", "只会有规则摘要")
                # Compare with .env expectations.
                if provided.get("base_url") and dotenv.get("DEEPSEEK_BASE_URL"):
                    if provided["base_url"].rstrip("/") != dotenv["DEEPSEEK_BASE_URL"].rstrip("/"):
                        add(
                            "FAIL",
                            "服务端 DeepSeek base_url 与 .env 不一致",
                            f"health={provided['base_url']} .env={dotenv['DEEPSEEK_BASE_URL']}；"
                            "旧进程未替换或启动环境变量覆盖",
                        )
                expected_model = dotenv.get("LLM_MODEL", "").strip()
                if expected_model and provided.get("base_url", "").find("deepseek") >= 0:
                    if (health.get("settings") or {}).get("llm_model") not in {expected_model, ""}:
                        add(
                            "WARN",
                            "服务端 LLM_MODEL 与 .env 不一致",
                            f"health={(health.get('settings') or {}).get('llm_model')} .env={expected_model}",
                        )
        except httpx.HTTPError as exc:
            add("FAIL", "无法连接本地服务", f"{type(exc).__name__}: {exc}")
    else:
        print("\n[3] /api/health skipped")

    # ---- live LLM -------------------------------------------------------
    if not args.skip_live and deepseek:
        print("\n[4] DeepSeek live check")
        headers = {
            "Authorization": bearer_auth_header(deepseek.api_key),
            "Content-Type": "application/json",
        }
        targets = []
        if server_llm_base:
            targets.append(("server(health)", server_llm_base))
        if deepseek.base_url:
            targets.append(("resolved", deepseek.base_url))
        env_base = (dotenv.get("DEEPSEEK_BASE_URL") or "").rstrip("/")
        if env_base:
            targets.append((".env", env_base))
        seen_bases: set[str] = set()
        targets = [(label, base) for label, base in targets if not (base in seen_bases or seen_bases.add(base))]
        for label, base in targets:
            async with httpx.AsyncClient(
                base_url=base,
                timeout=httpx.Timeout(60.0, connect=10.0),
                headers=headers,
            ) as client:
                try:
                    models = await client.get("/models")
                    ok_models = models.status_code == 200
                    count = len((models.json().get("data") or [])) if ok_models else 0
                    line(f"models @ {label}", f"HTTP {models.status_code} count={count}")
                    body = {
                        "model": "deepseek-flash",
                        "messages": [
                            {"role": "system", "content": "只输出 JSON。"},
                            {"role": "user", "content": '返回 {"ok":true}，不要解释。'},
                        ],
                        "temperature": 0,
                        "max_tokens": 128,
                        "response_format": {"type": "json_object"},
                        "thinking": {"type": "disabled"},
                    }
                    chat = await client.post("/chat/completions", json=body)
                    if chat.status_code == 200:
                        payload = chat.json()
                        choice = (payload.get("choices") or [{}])[0]
                        content = (choice.get("message") or {}).get("content") or ""
                        finish = choice.get("finish_reason")
                        valid = False
                        try:
                            valid = isinstance(_extract_json(content), dict)
                        except Exception:
                            valid = False
                        line(f"chat @ {label}", f"HTTP 200 finish={finish} json={valid} chars={len(content)}")
                        if not valid:
                            line(f"  content @ {label}", repr(content[:120]))
                        if not valid and label in {"resolved", "server(health)"}:
                            add("FAIL", f"LLM 不能返回严格 JSON ({label})", f"finish={finish} chars={len(content)}")
                    else:
                        line(f"chat @ {label}", f"HTTP {chat.status_code} {chat.text[:100]}")
                        if label in {"resolved", "server(health)"}:
                            add("FAIL", f"LLM 调用失败 ({label})", f"HTTP {chat.status_code}: {chat.text[:140]}")
                except httpx.HTTPError as exc:
                    line(f"live @ {label}", f"TRANSPORT {type(exc).__name__}")
                    if label in {"resolved", "server(health)"}:
                        add("FAIL", f"LLM 连接失败 ({label})", f"{type(exc).__name__}: {exc}")

    # ---- live SearchPro -------------------------------------------------
    if not args.skip_live and settings.search_api_key:
        print("\n[5] SearchPro parameter check")
        headers = {
            "Content-Type": "application/json; charset=UTF-8",
            "Authorization": bearer_auth_header(settings.search_api_key),
        }
        base = settings.search_base_url
        cases = [
            ("baseline 西安城墙", {"Query": "西安城墙 历史沿革", "Cnt": "20", "Mode": 0}),
            ("Site exactly www.xa.gov.cn", {"Query": "西安城墙", "Cnt": "20", "Mode": 0, "Site": "www.xa.gov.cn"}),
            ("Site apex xa.gov.cn", {"Query": "西安城墙", "Cnt": "20", "Mode": 0, "Site": "xa.gov.cn"}),
            ("Site gov.cn", {"Query": "西安城墙", "Cnt": "20", "Mode": 0, "Site": "gov.cn"}),
            ("Industry=gov", {"Query": "西安城墙 历史沿革", "Cnt": "20", "Mode": 0, "Industry": "gov"}),
            ("Freshness=y1", {"Query": "西安城墙 历史沿革", "Cnt": "20", "Mode": 0, "Freshness": "y1"}),
        ]
        async with httpx.AsyncClient(
            base_url=base, timeout=httpx.Timeout(30.0, connect=10.0), headers=headers
        ) as client:
            results: dict[str, int] = {}
            for label, body in cases:
                try:
                    resp = await client.post("/SearchPro", json=body)
                    if resp.status_code != 200:
                        line(label, f"HTTP {resp.status_code} {resp.text[:120]}")
                        results[label] = -1
                        continue
                    request = SearchRequest(
                        query=str(body.get("Query") or ""),
                        site=body.get("Site"),
                        industry=body.get("Industry"),
                        freshness=body.get("Freshness"),
                        cnt=20,
                    )
                    batch = normalize_api_response(resp.json(), "diag", 0.0, request)
                    results[label] = len(batch.pages)
                    line(
                        label,
                        f"pages={len(batch.pages):2} version={batch.version or '-':9} "
                        f"reqid={(batch.request_id[:8] if batch.request_id else '-')} error={batch.error}",
                    )
                except httpx.HTTPError as exc:
                    line(label, f"TRANSPORT {type(exc).__name__}")
                    results[label] = -1
        baseline = results.get("baseline 西安城墙", 0)
        exact = results.get("Site exactly www.xa.gov.cn", 0)
        apex = results.get("Site apex xa.gov.cn", 0)
        if baseline <= 0:
            add("FAIL", "SearchPro 基线查询无结果", "检查 key/额度/网络")
        if exact <= 0:
            add("WARN", "Site 精确 host 无结果", "该 host 可能未被索引，或 Site 不受支持")
        if apex > 0:
            add("WARN", "Site apex 有结果", "与历史观察不同；请复核 host 规则")
        elif exact > 0:
            print("  note: Site 需要与索引 host 完全一致（www 前缀不能省略）")

    # ---- planner --------------------------------------------------------
    if args.plan and args.base_url:
        print(f"\n[6] /api/plan at {args.base_url}")
        text = args.plan_text or "西安城墙是全国唯一保存完整的唐代城墙，唐朝原汁原味，城砖都是唐代的，所以西安城墙是世界文化遗产。"
        try:
            async with httpx.AsyncClient(base_url=args.base_url, timeout=httpx.Timeout(120.0, connect=10.0)) as client:
                resp = await client.post("/api/plan", json={"text": text})
            if resp.status_code != 200:
                add("FAIL", "计划接口失败", f"HTTP {resp.status_code}: {resp.text[:160]}")
            else:
                data = resp.json()
                line("method", data.get("method"))
                line("requirements", len(data.get("requirements") or []))
                line("queries", len(data.get("queries") or []))
                for req in (data.get("requirements") or [])[:3]:
                    line("  field/focus", f"{req.get('field')} / {str(req.get('focus'))[:40]}")
                    line("  search_terms", req.get("search_terms"))
                if data.get("method") != "llm":
                    add("FAIL", "计划退化为 heuristic", "LLM 不可用或返回非法 JSON；见服务日志")
        except httpx.HTTPError as exc:
            add("FAIL", "计划接口无法连接", f"{type(exc).__name__}: {exc}")

    # ---- verdict --------------------------------------------------------
    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    if not findings:
        print("  PASS: no FAIL/WARN detected")
    else:
        for level, title, detail in findings:
            print(f"  {level:<4} {title}: {detail}")
    fails = sum(1 for item in findings if item[0] == "FAIL")
    print(f"\n  FAIL={fails} WARN={sum(1 for item in findings if item[0] == 'WARN')}")
    return {"findings": findings}, overrides


def main() -> int:
    global args
    parser = argparse.ArgumentParser(description="Diagnose claimlab connections and effective config")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="local API base (default 8000)")
    parser.add_argument("--skip-live", action="store_true", help="only compare .env and /api/health")
    parser.add_argument("--plan", action="store_true", help="also POST /api/plan (uses LLM, no search budget)")
    parser.add_argument("--plan-text", default="", help="question for --plan")
    args = parser.parse_args()
    result, _ = asyncio.run(async_main())
    fails = sum(1 for item in result["findings"] if item[0] == "FAIL")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
