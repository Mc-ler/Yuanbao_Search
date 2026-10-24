"""FastAPI delivery layer: deep research, claim verification, reports and UI."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from . import __version__
from .config import Settings, load_settings
from .contracts import ResearchTask, jsonable
from .envfile import read_env, upsert, write_env
from .keys import normalize_base_url, strip_bearer
from .llm.client import build_llm
from .logging import configure_logging, event
from .planning import build_research_plan
from .research import run_research
from .runtime import build_sandbox
from .search.api import ApiSearchProvider
from .runs import RunRecord, RunStore
from .skills.reporting import render_markdown
from .skills.safety import SafetyError, check_task


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunRequest(StrictModel):
    text: str = Field(min_length=1, max_length=4000)
    search_off: bool = False


class CancelResponse(BaseModel):
    run_id: str
    cancelled: bool


class PlanRequest(StrictModel):
    text: str = Field(min_length=1, max_length=4000)
    refresh: bool = False


class ResearchRequest(StrictModel):
    text: str = Field(min_length=1, max_length=4000)
    refresh: bool = False
    plan_id: str | None = None


class LLMConfigRequest(StrictModel):
    provider: Literal["deepseek", "gpt", "codex"] = "deepseek"
    api_key: str | None = Field(default=None, max_length=512)
    base_url: str | None = Field(default=None, max_length=300)
    model: str | None = Field(default=None, max_length=100)


class SearchConfigRequest(StrictModel):
    api_key: str | None = Field(default=None, max_length=512)
    base_url: str | None = Field(default=None, max_length=300)


class ScreenshotConfigRequest(StrictModel):
    enabled: bool


SKILLS = [
    {"id": "S1", "name": "requirement-decomposition", "title": "需求拆分", "detail": "研究问题 → 1–3 个可检索需求", "applies_to": ["deep"]},
    {"id": "S2", "name": "query-planning", "title": "查询构造", "detail": "需求 → 精准/模糊查询方案", "applies_to": ["deep", "verify"]},
    {"id": "S3", "name": "search-gateway", "title": "检索网关", "detail": "API 单通道、缓存、预算、审计", "applies_to": ["deep", "verify"]},
    {"id": "S4", "name": "evidence-dedup", "title": "去重成簇", "detail": "5-gram + Jaccard，按簇计票", "applies_to": ["deep", "verify"]},
    {"id": "S5", "name": "source-grading", "title": "来源分级", "detail": "A–E，域名 + 时效", "applies_to": ["deep", "verify"]},
    {"id": "S6", "name": "evidence-matching", "title": "证据匹配", "detail": "支持/反驳/无关 + 原文引用校验", "applies_to": ["verify"]},
    {"id": "S7", "name": "claim-judging", "title": "字典序判定", "detail": "R1–R5，分层结论", "applies_to": ["verify"]},
    {"id": "S8", "name": "report-writing", "title": "报告生成", "detail": "研究综述 + 判定报告", "applies_to": ["deep", "verify"]},
    {"id": "S9", "name": "safety-guard", "title": "安全红线", "detail": "时政/个人/长度 + 截图 SSRF", "applies_to": ["deep", "verify"]},
]


def _validate_text(text: str) -> str:
    cleaned = (text or "").strip()
    try:
        check_task(ResearchTask(text=cleaned))
    except SafetyError as exc:
        raise HTTPException(status_code=400, detail=exc.reason) from exc
    return cleaned


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", (text or "")).strip().lower()


def _csv_safe(value: Any) -> str:
    text = str(value or "")
    if text.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def create_app(settings: Settings | None = None, sandbox: Any | None = None) -> FastAPI:
    settings = settings or load_settings()
    settings.ensure_dirs()
    log_path = configure_logging(
        settings.logs_dir,
        f"app-{datetime.now():%Y%m%d}.log",
        level=settings.log_level,
        max_bytes=settings.log_max_bytes,
        backup_count=settings.log_backup_count,
    )
    api_log = logging.getLogger("claimlab.api")
    event(api_log, "app.start", version=__version__, log=log_path, search_provider=settings.search_provider)
    sandbox = sandbox or build_sandbox(settings)
    store = RunStore()
    semaphore = asyncio.Semaphore(max(1, settings.max_concurrent_research))
    verify_semaphore = asyncio.Semaphore(max(1, settings.max_concurrent_research))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        await sandbox.close()

    app = FastAPI(
        title="说法鉴定所 / YuanBao Research Agent",
        version=__version__,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.sandbox = sandbox
    app.state.store = store

    async def execute(record: RunRecord) -> None:
        pipeline = sandbox.new_pipeline(on_event=lambda event: store.publish(record.run_id, event))
        try:
            async with verify_semaphore:
                report = await pipeline.run(
                    record.task,
                    cancel_event=record.cancel,
                    run_id=record.run_id,
                    search_off=record.search_off,
                )
            store.finish(record.run_id, report)
            if record.status == "cancelling":
                record.status = "cancelled"
        except Exception as exc:
            event(api_log, "run.error", run_id=record.run_id, error=f"{type(exc).__name__}: {exc}")
            store.fail(record.run_id, f"{type(exc).__name__}: {exc}")

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        payload = await sandbox.health()
        payload["version"] = __version__
        payload["runs"] = len(store.runs)
        payload["fixtures"] = len(sandbox.fixtures)
        payload["search_off_available"] = True
        payload["search_ready"] = settings.search_ready
        payload["llm_ready"] = bool((payload.get("llm") or {}).get("key_present"))
        payload["screenshots_ready"] = sandbox.screenshots.enabled
        return payload

    def _save_updates(updates: dict[str, str]) -> None:
        path = settings.root / ".env"
        lines = read_env(path)
        for key, value in updates.items():
            upsert(lines, key, value)
            os.environ[key] = value
        write_env(path, lines)

    def _checked_base_url(value: str) -> str:
        parts = urlsplit(value.strip())
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise HTTPException(status_code=400, detail="Base URL 必须是 http(s) 地址")
        return normalize_base_url(value.strip())

    @app.post("/api/config/llm")
    async def config_llm(request: LLMConfigRequest) -> dict[str, Any]:
        prefix = {"deepseek": "DEEPSEEK", "gpt": "GPT", "codex": "CODEX"}[request.provider]
        updates: dict[str, str] = {"LLM_PROVIDER": request.provider}
        if request.api_key is not None:
            updates[f"{prefix}_API_KEY"] = strip_bearer(request.api_key.strip())
        if request.base_url:
            updates[f"{prefix}_BASE_URL"] = _checked_base_url(request.base_url)
        if request.model and request.model.strip():
            updates["LLM_MODEL"] = request.model.strip()
        _save_updates(updates)
        settings.llm_provider = request.provider
        if request.model and request.model.strip():
            settings.llm_model = request.model.strip()
        old_llm = sandbox.llm
        try:
            sandbox.llm = build_llm(settings)
        except Exception as exc:
            sandbox.llm = old_llm
            event(api_log, "config.llm.error", provider=request.provider, error=type(exc).__name__)
            raise HTTPException(status_code=400, detail=f"LLM 配置失败: {type(exc).__name__}") from exc
        try:
            await old_llm.close()
        except Exception:
            pass
        event(api_log, "config.llm", provider=request.provider, key_present=settings.llm_key_present)
        return {
            "ok": True,
            "provider": settings.llm_provider,
            "model": settings.llm_model or None,
            "key_present": settings.llm_key_present,
        }

    @app.post("/api/config/search")
    async def config_search(request: SearchConfigRequest) -> dict[str, Any]:
        updates: dict[str, str] = {}
        if request.api_key is not None:
            updates["SEARCH_API_KEY"] = strip_bearer(request.api_key.strip())
        if request.base_url:
            updates["SEARCH_BASE_URL"] = _checked_base_url(request.base_url)
        _save_updates(updates)
        if request.api_key is not None:
            settings.search_api_key = strip_bearer(request.api_key.strip())
        if request.base_url:
            settings.search_base_url = _checked_base_url(request.base_url)
        old_providers = list(sandbox.providers.values())
        sandbox.providers = (
            {"api": ApiSearchProvider(settings)} if settings.search_api_key else {}
        )
        settings.search_provider = "api"
        for provider in old_providers:
            try:
                await provider.close()
            except Exception:
                pass
        event(api_log, "config.search", key_present=settings.search_key_present)
        return {
            "ok": True,
            "key_present": settings.search_key_present,
            "base_url": settings.search_base_url,
        }

    @app.post("/api/config/screenshots")
    async def config_screenshots(request: ScreenshotConfigRequest) -> dict[str, Any]:
        capturer = sandbox.screenshots
        if request.enabled:
            if not capturer.chrome:
                raise HTTPException(status_code=400, detail="未找到 Chrome/Edge，无法启用截图")
            if "websockets" in (capturer.reason or ""):
                raise HTTPException(status_code=400, detail="websockets 未安装，无法启用截图")
        settings.screenshot_enabled = request.enabled
        capturer.enabled = bool(request.enabled and capturer.chrome)
        capturer.reason = "" if capturer.enabled else (
            "EVIDENCE_SCREENSHOTS disabled" if not request.enabled else capturer.reason
        )
        _save_updates({"EVIDENCE_SCREENSHOTS": "true" if request.enabled else "false"})
        event(api_log, "config.screenshots", enabled=request.enabled)
        return {"ok": True, "enabled": capturer.enabled, "reason": capturer.reason}

    @app.get("/api/skills")
    async def skills() -> list[dict[str, Any]]:
        return SKILLS

    @app.post("/api/plan")
    async def plan_query(request: PlanRequest) -> dict[str, Any]:
        text = _validate_text(request.text)
        plan = await build_research_plan(sandbox.llm, text)
        sandbox.plan_store.put(plan)
        event(api_log, "plan.done", text_len=len(text), requirements=len(plan.items))
        return {
            "plan_id": plan.plan_id,
            "domain": plan.domain,
            "method": plan.method,
            "requirements": jsonable([item.requirement for item in plan.items]),
            "queries": jsonable(plan.all_queries()),
            "fallback_queries": jsonable(plan.all_fallbacks()),
            "requery_queries": jsonable(plan.all_requeries()),
        }

    @app.post("/api/research")
    async def research(request: ResearchRequest) -> dict[str, Any]:
        if not settings.search_ready:
            raise HTTPException(status_code=503, detail="未配置 SEARCH_API_KEY；无法执行真实检索")
        text = _validate_text(request.text)
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=5)
        except asyncio.TimeoutError:
            raise HTTPException(status_code=429, detail="当前研究任务较多，请等待当前任务完成后再试")
        try:
            plan = None
            plan_reused = False
            if request.plan_id:
                plan = sandbox.plan_store.get(request.plan_id)
                if plan is not None:
                    if _normalize_text(plan.text) != _normalize_text(text):
                        raise HTTPException(status_code=400, detail="plan_id 与 text 不匹配，请重新生成查询计划")
                    plan_reused = True
            if plan is None:
                plan = await build_research_plan(sandbox.llm, text)
                sandbox.plan_store.put(plan)
            event(api_log, "research.start", text_len=len(text), plan_id=plan.plan_id, plan_reused=plan_reused)
            try:
                payload = await asyncio.wait_for(
                    run_research(sandbox, text, plan=plan, refresh=request.refresh),
                    timeout=max(30, settings.research_timeout_seconds),
                )
            except asyncio.TimeoutError as exc:
                raise HTTPException(
                    status_code=504,
                    detail=f"研究超时（>{settings.research_timeout_seconds}s）；请减少截图或稍后重试",
                ) from exc
        except HTTPException:
            raise
        except Exception as exc:
            event(api_log, "research.error", error=f"{type(exc).__name__}: {exc}")
            raise HTTPException(status_code=502, detail=f"research failed: {type(exc).__name__}: {exc}") from exc
        finally:
            semaphore.release()
        payload["plan_reused"] = plan_reused
        event(
            api_log,
            "research.done",
            run_id=payload.get("run_id"),
            plan_id=plan.plan_id,
            requirements=payload["metrics"]["requirements"],
            pages=payload["metrics"]["pages_unique"],
            ab=payload["metrics"]["requirements_with_ab"],
        )
        return jsonable(payload)

    @app.get("/api/evidence/{run_id}/{number}")
    async def evidence(run_id: str, number: int) -> Response:
        record = sandbox.evidence_images.get(run_id, number)
        if record is None:
            raise HTTPException(status_code=404, detail="evidence image not found or expired")
        return Response(
            content=record.data,
            media_type=record.media_type,
            headers={"Cache-Control": "private, max-age=600"},
        )

    @app.post("/api/runs")
    async def create_run(request: RunRequest) -> dict[str, Any]:
        if not settings.search_ready:
            raise HTTPException(status_code=503, detail="未配置 SEARCH_API_KEY；无法执行真实检索")
        text = _validate_text(request.text)
        task = ResearchTask(text=text, mode="verify_claim")
        event(api_log, "run.create", run_id="pending", text_len=len(text), search_off=request.search_off)
        record = store.create(task, search_off=request.search_off)
        record.handle = asyncio.create_task(execute(record))
        return {"run_id": record.run_id, "status": record.status}

    @app.get("/api/db/stats")
    async def db_stats() -> dict[str, Any]:
        return sandbox.store.stats()

    @app.get("/api/db/runs")
    async def db_runs(q: str = "", limit: int = 50, offset: int = 0) -> dict[str, Any]:
        return sandbox.store.query_runs(q=q, limit=limit, offset=offset)

    @app.get("/api/db/runs/{run_id}")
    async def db_run_detail(run_id: str) -> dict[str, Any]:
        row = sandbox.store.get_run(run_id)
        if row is None:
            raise HTTPException(status_code=404, detail="run not found")
        return row

    @app.get("/api/db/export.csv")
    async def db_export(q: str = "") -> Response:
        import csv
        import io

        rows = sandbox.store.export_rows(q=q)
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["run_id", "question", "subject", "city", "domain", "method", "status", "created_at"])
        for row in rows:
            writer.writerow(
                [
                    _csv_safe(row.get("run_id", "")),
                    _csv_safe(row.get("question", "")),
                    _csv_safe(row.get("subject", "")),
                    _csv_safe(row.get("city", "")),
                    _csv_safe(row.get("domain", "")),
                    _csv_safe(row.get("method", "")),
                    _csv_safe(row.get("status", "")),
                    _csv_safe(row.get("created_at", "")),
                ]
            )
        return Response(
            content="\ufeff" + buf.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=runs.csv"},
        )

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, Any]:
        record = store.get(run_id)
        if record is None:
            raise HTTPException(status_code=404, detail="run not found")
        return record.snapshot()

    @app.post("/api/runs/{run_id}/cancel", response_model=CancelResponse)
    async def cancel_run(run_id: str) -> CancelResponse:
        if store.get(run_id) is None:
            raise HTTPException(status_code=404, detail="run not found")
        return CancelResponse(run_id=run_id, cancelled=store.cancel(run_id))

    @app.get("/api/runs/{run_id}/events")
    async def run_events(run_id: str) -> StreamingResponse:
        if store.get(run_id) is None:
            raise HTTPException(status_code=404, detail="run not found")

        async def stream():
            async for item in store.events(run_id):
                if item.get("type") == "ping":
                    yield ": ping\n\n"
                    continue
                event_type = str(item.get("type") or "message")
                data = json.dumps(item, ensure_ascii=False)
                yield f"event: {event_type}\ndata: {data}\n\n"

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/report/{run_id}")
    async def report(run_id: str, format: str = "json"):
        record = store.get(run_id)
        if record is None:
            raise HTTPException(status_code=404, detail="run not found")
        if record.report_obj is None:
            if record.report is None:
                raise HTTPException(status_code=409, detail="run has no report yet")
            return record.report
        if format == "md":
            return PlainTextResponse(render_markdown(record.report_obj), media_type="text/markdown; charset=utf-8")
        return record.report or jsonable(record.report_obj)

    @app.get("/")
    async def index() -> FileResponse:
        target = settings.web_dir / "index.html"
        if not target.exists():
            raise HTTPException(status_code=404, detail="web/index.html not found")
        return FileResponse(target)

    @app.get("/rules")
    async def rules() -> FileResponse:
        target = settings.web_dir / "rules.html"
        if not target.exists():
            raise HTTPException(status_code=404, detail="web/rules.html not found")
        return FileResponse(target)

    app.mount("/static", StaticFiles(directory=str(settings.web_dir)), name="static")
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=app.state.settings.app_host,
        port=app.state.settings.app_port,
        timeout_keep_alive=75,
    )
