"""In-memory run registry and SSE event streams.

This is a technical job store for the API, not a knowledge base. The
append-only audit archive stays write-only; the registry exists so the UI
can reconnect, replay and cancel a live run.
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, field
from typing import AsyncIterator

from .contracts import ResearchReport, ResearchTask, now_iso


@dataclass
class RunRecord:
    run_id: str
    task: ResearchTask
    search_off: bool = False
    status: str = "running"  # running | cancelling | done | error | cancelled
    events: list[dict] = field(default_factory=list)
    report: dict | None = None
    report_obj: ResearchReport | None = None
    error: str | None = None
    created_at: str = field(default_factory=now_iso)
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    queues: list[asyncio.Queue] = field(default_factory=list)
    handle: asyncio.Task | None = None

    def snapshot(self) -> dict:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "created_at": self.created_at,
            "task": {
                "text": self.task.text,
                "subject": self.task.subject,
                "city": self.task.city,
                "mode": self.task.mode,
                "fixture_id": self.task.fixture_id,
            },
            "search_off": self.search_off,
            "events": len(self.events),
            "report": self.report,
            "error": self.error,
        }


class RunStore:
    def __init__(self, max_runs: int = 50) -> None:
        self.runs: dict[str, RunRecord] = {}
        self.max_runs = max_runs

    def create(self, task: ResearchTask, search_off: bool = False) -> RunRecord:
        run_id = f"run-{secrets.token_hex(6)}"
        record = RunRecord(run_id=run_id, task=task, search_off=search_off)
        self.runs[run_id] = record
        self._prune()
        return record

    def _prune(self) -> None:
        if len(self.runs) <= self.max_runs:
            return
        finished = [record for record in self.runs.values() if record.status in {"done", "error", "cancelled"}]
        for record in sorted(finished, key=lambda item: item.created_at)[: max(0, len(self.runs) - self.max_runs)]:
            self.runs.pop(record.run_id, None)

    def get(self, run_id: str) -> RunRecord | None:
        return self.runs.get(run_id)

    def publish(self, run_id: str, event: dict) -> None:
        record = self.runs.get(run_id)
        if record is None:
            return
        event = dict(event)
        event.setdefault("seq", len(record.events) + 1)
        record.events.append(event)
        if event.get("type") == "run.done":
            record.status = "done"
            record.report = event.get("report")
        elif event.get("type") == "error":
            record.status = "error"
            record.error = str(event.get("message") or "run failed")
        for queue in list(record.queues):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def finish(self, run_id: str, report: ResearchReport) -> None:
        record = self.runs.get(run_id)
        if record is None:
            return
        record.report_obj = report
        if record.status == "running":
            record.status = "done"
        if record.report is None:
            from .contracts import jsonable

            record.report = jsonable(report)

    def fail(self, run_id: str, message: str) -> None:
        record = self.runs.get(run_id)
        if record is None:
            return
        record.error = message
        record.status = "error"
        self.publish(run_id, {"type": "error", "message": message, "ts": now_iso()})

    def cancel(self, run_id: str) -> bool:
        record = self.runs.get(run_id)
        if record is None or record.status not in {"running", "cancelling"}:
            return False
        record.status = "cancelling"
        record.cancel.set()
        self.publish(run_id, {"type": "run.cancelling", "ts": now_iso()})
        return True

    async def events(self, run_id: str) -> AsyncIterator[dict]:
        record = self.get(run_id)
        if record is None:
            return
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        record.queues.append(queue)
        seen: set[int] = set()
        try:
            for event in list(record.events):
                seq = int(event.get("seq") or 0)
                seen.add(seq)
                yield event
                if event.get("type") in {"run.done", "error"}:
                    return
            while True:
                if record.status in {"done", "error", "cancelled"} and queue.empty():
                    return
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield {"type": "ping"}
                    continue
                seq = int(event.get("seq") or 0)
                if seq in seen:
                    continue
                seen.add(seq)
                yield event
                if event.get("type") in {"run.done", "error"}:
                    return
        finally:
            if queue in record.queues:
                record.queues.remove(queue)
