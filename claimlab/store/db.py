"""SQLite index over the JSONL archive for research runs.

Files stay authoritative; the database is an index + result copy used for
history search, stats and CSV export. Any DB failure degrades to pure file
mode and never blocks a run (mirrors the 1024 platform design).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

_WRITE_LOCK = threading.RLock()

DDL = [
    """CREATE TABLE IF NOT EXISTS runs (
        run_id       TEXT PRIMARY KEY,
        mode         TEXT NOT NULL DEFAULT '',
        question     TEXT NOT NULL DEFAULT '',
        subject      TEXT,
        city         TEXT,
        domain       TEXT,
        method       TEXT,
        status       TEXT NOT NULL DEFAULT 'done',
        metrics_json TEXT,
        result_json  TEXT,
        created_at   TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE IF NOT EXISTS sources (
        source_id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id    TEXT NOT NULL,
        field     TEXT,
        url       TEXT,
        domain    TEXT,
        grade     TEXT,
        title     TEXT,
        date      TEXT,
        passage   TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_sources_run ON sources(run_id)",
    "CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at DESC)",
]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Store:
    """Minimal SQLite index; available is False when initialization fails."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.available = False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.path), timeout=10.0, check_same_thread=False)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                for sql in DDL:
                    conn.execute(sql)
                conn.commit()
                self.available = True
            finally:
                conn.close()
        except Exception:
            self.available = False

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.path), timeout=10.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def upsert_run(self, run_id, *, mode="", question="", subject=None, city=None,
                   domain="", method="", metrics=None, result=None) -> bool:
        if not self.available:
            return False
        try:
            with _WRITE_LOCK:
                conn = self._connect()
                try:
                    conn.execute(
                        "INSERT INTO runs(run_id, mode, question, subject, city, domain, method,"
                        " status, metrics_json, result_json, created_at)"
                        " VALUES(?,?,?,?,?,?,?,?,?,?,?)"
                        " ON CONFLICT(run_id) DO UPDATE SET"
                        " mode=excluded.mode, question=excluded.question, subject=excluded.subject,"
                        " city=excluded.city, domain=excluded.domain, method=excluded.method,"
                        " metrics_json=excluded.metrics_json, result_json=excluded.result_json",
                        (run_id, mode, question, subject, city, domain, method, "done",
                         json.dumps(metrics, ensure_ascii=False) if metrics is not None else None,
                         json.dumps(result, ensure_ascii=False) if result is not None else None,
                         _now()),
                    )
                    conn.commit()
                finally:
                    conn.close()
            return True
        except Exception:
            return False

    def upsert_sources(self, run_id: str, sources: list) -> bool:
        if not self.available:
            return False
        try:
            with _WRITE_LOCK:
                conn = self._connect()
                try:
                    conn.execute("DELETE FROM sources WHERE run_id = ?", (run_id,))
                    for src in sources or []:
                        conn.execute(
                            "INSERT INTO sources(run_id, field, url, domain, grade, title, date, passage)"
                            " VALUES(?,?,?,?,?,?,?,?)",
                            (run_id, str(src.get("field") or ""), str(src.get("url") or ""),
                             str(src.get("domain") or ""), str(src.get("grade") or ""),
                             str(src.get("title") or ""), str(src.get("date") or ""),
                             str(src.get("passage") or "")),
                        )
                    conn.commit()
                finally:
                    conn.close()
            return True
        except Exception:
            return False

    def stats(self) -> dict:
        if not self.available:
            return {"available": False}
        try:
            conn = self._connect()
            try:
                runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
                sources = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
                by_field = {}
                for row in conn.execute("SELECT field, COUNT(*) FROM sources GROUP BY field"):
                    by_field[row[0] or ""] = row[1]
                return {"available": True, "backend": "sqlite", "db_path": str(self.path),
                        "runs": runs, "sources": sources, "sources_by_field": by_field}
            finally:
                conn.close()
        except Exception:
            return {"available": False}

    def query_runs(self, q: str = "", limit: int = 50, offset: int = 0) -> dict:
        limit = max(1, min(int(limit or 50), 200))
        offset = max(0, int(offset or 0))
        if not self.available:
            return {"available": False, "runs": [], "total": 0}
        try:
            conn = self._connect()
            try:
                where = ""
                params = []
                if q:
                    where = "WHERE question LIKE ? OR run_id LIKE ?"
                    params = ["%" + q + "%", "%" + q + "%"]
                total = conn.execute("SELECT COUNT(*) FROM runs " + where, params).fetchone()[0]
                rows = conn.execute(
                    "SELECT run_id, question, subject, city, domain, method, status, created_at FROM runs "
                    + where + " ORDER BY created_at DESC, run_id DESC LIMIT ? OFFSET ?",
                    params + [limit, offset],
                ).fetchall()
                return {"available": True, "runs": [dict(r) for r in rows], "total": total}
            finally:
                conn.close()
        except Exception:
            return {"available": False, "runs": [], "total": 0}

    def get_run(self, run_id: str):
        if not self.available:
            return None
        try:
            conn = self._connect()
            try:
                row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
                if not row:
                    return None
                run = dict(row)
                run["metrics"] = json.loads(run.pop("metrics_json") or "{}")
                run["result"] = json.loads(run.pop("result_json") or "null") if run.get("result_json") else None
                sources = conn.execute(
                    "SELECT field, url, domain, grade, title, date, passage FROM sources WHERE run_id = ?",
                    (run_id,),
                ).fetchall()
                run["sources"] = [dict(s) for s in sources]
                return run
            finally:
                conn.close()
        except Exception:
            return None

    def export_rows(self, q: str = "", limit: int = 5000) -> list:
        limit = max(1, min(int(limit or 5000), 5000))
        if not self.available:
            return []
        try:
            conn = self._connect()
            try:
                where = ""
                params = []
                if q:
                    where = "WHERE question LIKE ? OR run_id LIKE ?"
                    params = ["%" + q + "%", "%" + q + "%"]
                rows = conn.execute(
                    "SELECT run_id, question, subject, city, domain, method, status, created_at FROM runs "
                    + where + " ORDER BY created_at DESC, run_id DESC LIMIT ?",
                    params + [limit],
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()
        except Exception:
            return []
