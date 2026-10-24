"""FastAPI delivery layer: run creation, SSE stream, report and static UI."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from .config import ROOT, Settings, load_settings
from .contracts import ResearchTask, dumps, jsonable
from .logging import configure_logging, event
from .research import run_research
from .runtime import build_sandbox
from .runs import RunRecord, RunStore
from .skills.query import (
    plan_fallback_queries,
    plan_key,
    plan_requery_queries,
    plan_requirement_queries,
)
from .skills.reporting import render_markdown
from .skills.requirements import decompose_requirements
from .store.fixtures import fixture_public_list


class RunRequest(BaseModel):
    text: str | None = None
    subject: str | None = None
    city: str | None = None
    fixture_id: str | None = None
    mode: str = "verify_claim"
    search_off: bool = False


class CancelResponse(BaseModel):
    run_id: str
    cancelled: bool


class PlanRequest(BaseModel):
    """Request for the downstream query-planning interface (no search)."""

    text: str | None = None
    subject: str | None = None
    city: str | None = None
    example_id: str | None = None
    mode: str = "research_topic"


class ResearchRequest(BaseModel):
    text: str | None = None
    subject: str | None = None
    city: str | None = None
    example_id: str | None = None
    refresh: bool = False


SKILLS = [
    {"id": "S1", "name": "requirement-decomposition", "title": "需求拆分", "detail": "研究问题 → 1–3 个可检索需求，直接接入查询构造"},
    {"id": "S2", "name": "query-planning", "title": "查询构造", "detail": "需求 → 精准/模糊查询方案"},
    {"id": "S3", "name": "search-gateway", "title": "检索网关", "detail": "API 单通道、缓存、预算、审计"},
    {"id": "S4", "name": "evidence-dedup", "title": "去重成簇", "detail": "5-gram + Jaccard，按簇计票"},
    {"id": "S5", "name": "source-grading", "title": "来源分级", "detail": "A–E，域名 + 时效，不看模型心情"},
    {"id": "S6", "name": "evidence-matching", "title": "证据匹配", "detail": "支持/反驳/无关 + 原文引用校验"},
    {"id": "S7", "name": "claim-judging", "title": "字典序判定", "detail": "R1–R5，分层结论"},
    {"id": "S8", "name": "report-writing", "title": "报告生成", "detail": "契约 C，引用与行动含义"},
    {"id": "S9", "name": "safety-guard", "title": "安全红线", "detail": "主体白名单、措辞、个人信息"},
]


def create_app(settings: Settings | None = None) -> FastAPI:
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
    sandbox = build_sandbox(settings)
    store = RunStore()

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
            report = await pipeline.run(
                record.task,
                cancel_event=record.cancel,
                run_id=record.run_id,
                search_off=record.search_off,
            )
            store.finish(record.run_id, report)
            if record.status == "cancelling":
                record.status = "cancelled"
        except Exception as exc:  # keep the SSE stream informative
            event(api_log, "run.error", run_id=record.run_id, error=f"{type(exc).__name__}: {exc}")
            store.fail(record.run_id, f"{type(exc).__name__}: {exc}")

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        payload = await sandbox.health()
        payload["version"] = __version__
        payload["runs"] = len(store.runs)
        payload["fixtures"] = len(sandbox.fixtures)
        payload["search_off_available"] = True
        return payload

    @app.get("/api/fixtures")
    async def fixtures() -> list[dict[str, Any]]:
        return fixture_public_list(sandbox.fixtures)

    @app.get("/api/skills")
    async def skills() -> list[dict[str, Any]]:
        return SKILLS

    examples_dir = ROOT / "examples"

    def load_example(example_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", example_id or ""):
            raise HTTPException(status_code=404, detail="example not found")
        path = examples_dir / f"{example_id}.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"example not found: {example_id}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=500, detail=f"invalid example file: {example_id}") from exc
        if not isinstance(data, dict):
            raise HTTPException(status_code=500, detail=f"invalid example file: {example_id}")
        return data

    def resolve_research_input(request: Any) -> tuple[str, str | None, str | None, dict[str, Any]]:
        """Resolve research input so an example only seeds a question.

        When the caller supplies its own 'text', the example's subject/city and
        constraints are ignored; otherwise they act as defaults. This prevents a
        previously clicked example from leaking subject/city/domain into an
        unrelated question typed afterwards.
        """
        example = load_example(request.example_id) if getattr(request, "example_id", None) else {}
        text = (request.text or str(example.get("question") or "")).strip()
        from_example = not request.text
        subject = (request.subject or (str(example.get("subject") or "") if from_example else "")).strip() or None
        city = (request.city or (str(example.get("city") or "") if from_example else "")).strip() or None
        constraints = (
            {
                "domain": example.get("domain") or "",
                "expected_sources": example.get("expected_sources") or [],
                "query_fields": example.get("query_fields") or [],
            }
            if from_example
            else {}
        )
        return text, subject, city, constraints

    @app.get("/api/examples")
    async def examples() -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        if examples_dir.exists():
            for path in sorted(examples_dir.glob("*.json")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                if not isinstance(data, dict):
                    continue
                question = str(data.get("question") or "").strip()
                result.append(
                    {
                        "example_id": path.stem,
                        "domain": data.get("domain") or "",
                        "question_filled": bool(question),
                        "question": question,
                        "question_suggestion": data.get("question_suggestion") or "",
                        "subject": data.get("subject") or "",
                        "city": data.get("city") or "",
                        "notes": data.get("notes") or "",
                        "query_fields": data.get("query_fields") or [],
                        "expected_sources": data.get("expected_sources") or [],
                    }
                )
        return result

    @app.post("/api/plan")
    async def plan_query(request: PlanRequest) -> dict[str, Any]:
        text, subject, city, constraints = resolve_research_input(request)
        if not text:
            hint = request.example_id or "request.text"
            raise HTTPException(
                status_code=400,
                detail=f"question is empty; fill the question in examples/*.json or pass text ({hint})",
            )
        task = ResearchTask(
            text=text,
            mode="research_topic",
            subject=subject,
            city=city,
            constraints=constraints,
        )
        plan = await decompose_requirements(sandbox.llm, task)
        queries = []
        fallback_queries = []
        requery_queries = []
        used: set[tuple[str, str | None, str | None]] = set()
        for requirement in plan.requirements:
            initial = plan_requirement_queries(
                requirement,
                subject=subject,
                city=city,
                used=used,
            )
            queries.extend(initial)
            used.update(plan_key(item) for item in initial)
            fallback = plan_fallback_queries(requirement, subject=subject, city=city, used=used)
            fallback_queries.extend(fallback)
            used.update(plan_key(item) for item in fallback)
            requery = plan_requery_queries(requirement, subject=subject, city=city, used=used)
            requery_queries.extend(requery)
            used.update(plan_key(item) for item in requery)
        event(
            api_log,
            "plan.done",
            example_id=request.example_id,
            method=plan.method,
            requirements=len(plan.requirements),
            queries=len(queries),
            fallback_queries=len(fallback_queries),
            requery_queries=len(requery_queries),
        )
        return {
            "example_id": request.example_id,
            "domain": plan.domain,
            "method": plan.method,
            "requirements": jsonable(plan.requirements),
            "queries": jsonable(queries),
            "fallback_queries": jsonable(fallback_queries),
            "requery_queries": jsonable(requery_queries),
        }

    @app.post("/api/runs")
    async def create_run(request: RunRequest) -> dict[str, Any]:
        if request.mode != "verify_claim":
            raise HTTPException(status_code=400, detail="research_topic 请使用 /api/research")
        fixture = sandbox.fixtures.get(request.fixture_id or "") if request.fixture_id else None
        if request.fixture_id and fixture is None:
            raise HTTPException(status_code=404, detail=f"fixture not found: {request.fixture_id}")
        text = (request.text or (fixture or {}).get("text") or "").strip()
        if not text:
            raise HTTPException(status_code=400, detail="请输入一条文字说法")
        task = ResearchTask(
            text=text,
            mode="verify_claim",
            subject=request.subject or (fixture or {}).get("subject"),
            city=request.city or (fixture or {}).get("city"),
            fixture_id=request.fixture_id,
        )
        event(api_log, "run.create", run_id="pending", text_len=len(text), fixture_id=request.fixture_id, search_off=request.search_off)
        record = store.create(task, search_off=request.search_off)
        record.handle = asyncio.create_task(execute(record))
        return {"run_id": record.run_id, "status": record.status}

    @app.post("/api/research")
    async def research(request: ResearchRequest) -> dict[str, Any]:
        text, subject, city, constraints = resolve_research_input(request)
        if not text:
            raise HTTPException(
                status_code=400,
                detail="question is empty; fill the example question or pass text",
            )
        task = ResearchTask(
            text=text,
            mode="research_topic",
            subject=subject,
            city=city,
            constraints=constraints,
        )
        event(
            api_log,
            "research.start",
            example_id=request.example_id,
            text_len=len(text),
            subject=subject,
            city=city,
        )
        try:
            payload = await run_research(
                sandbox,
                task,
                example_id=request.example_id or "",
                refresh=request.refresh,
            )
        except Exception as exc:
            event(api_log, "research.error", error=f"{type(exc).__name__}: {exc}")
            raise HTTPException(status_code=502, detail=f"research failed: {type(exc).__name__}: {exc}") from exc
        event(
            api_log,
            "research.done",
            example_id=request.example_id,
            run_id=payload.get("run_id"),
            fields=payload["metrics"]["fields"],
            distinct_fields=payload["metrics"]["distinct_fields"],
            tier_ab=payload["metrics"]["fields_with_ab"],
        )
        return jsonable(payload)

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
                    row.get("run_id", ""),
                    row.get("question", ""),
                    row.get("subject", ""),
                    row.get("city", ""),
                    row.get("domain", ""),
                    row.get("method", ""),
                    row.get("status", ""),
                    row.get("created_at", ""),
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
            async for event in store.events(run_id):
                if event.get("type") == "ping":
                    yield ": ping\n\n"
                    continue
                event_type = str(event.get("type") or "message")
                data = json.dumps(event, ensure_ascii=False)
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

    uvicorn.run(app, host=app.state.settings.app_host, port=app.state.settings.app_port)
