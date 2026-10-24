"""Append-only JSONL audit log.

The runtime never reads this log. Fixtures and the technical cache are the
only replay inputs; the archive exists for post-hoc audit and evidence.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from ..contracts import jsonable, now_iso


class ArchiveWriter:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, run_id: str) -> Path:
        safe = "".join(ch for ch in run_id if ch.isalnum() or ch in "-_") or "run"
        return self.root / f"{safe}.jsonl"

    def write_event(self, run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        record = {"ts": now_iso(), "run_id": run_id, "type": event_type, "payload": jsonable(payload)}
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            with self._path(run_id).open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def write_search(
        self,
        run_id: str,
        request: dict[str, Any],
        batch: Any,
        provider: str,
        cache_hit: bool,
    ) -> None:
        self.write_event(
            run_id,
            "search",
            {
                "provider": provider,
                "cache_hit": cache_hit,
                "request": request,
                "response": {
                    "request_id": getattr(batch, "request_id", ""),
                    "version": getattr(batch, "version", ""),
                    "error": getattr(batch, "error", None),
                    "warnings": getattr(batch, "warnings", []),
                    "pages": [getattr(page, "__dict__", page) for page in getattr(batch, "pages", [])],
                    "raw": getattr(batch, "raw", None),
                },
            },
        )

    def write_llm(self, run_id: str, task: str, model: str, response: Any, cache_hit: bool) -> None:
        self.write_event(
            run_id,
            "llm",
            {"task": task, "model": model, "cache_hit": cache_hit, "response": response},
        )
