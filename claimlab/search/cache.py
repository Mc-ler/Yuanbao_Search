"""Small, atomic disk cache for search and LLM responses."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any

from ..contracts import jsonable
from ..fsutil import atomic_write_text


def cache_key(*parts: Any) -> str:
    raw = json.dumps(jsonable(parts), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class DiskCache:
    def __init__(self, root: Path, namespace: str, ttl_seconds: float) -> None:
        self.root = root / namespace
        self.root.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()

    def _path(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def get(self, key: str) -> Any | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        created = float(data.get("created_at", 0))
        if self.ttl_seconds > 0 and time.time() - created > self.ttl_seconds:
            return None
        return data.get("value")

    def set(self, key: str, value: Any) -> None:
        path = self._path(key)
        payload = {"created_at": time.time(), "value": jsonable(value)}
        with self._lock:
            atomic_write_text(path, json.dumps(payload, ensure_ascii=False))

    def has(self, key: str) -> bool:
        return self.get(key) is not None

    def stats(self) -> dict[str, Any]:
        files = list(self.root.glob("*.json"))
        return {"namespace": self.root.name, "entries": len(files), "ttl_seconds": self.ttl_seconds}

    def clear(self) -> None:
        with self._lock:
            for path in self.root.glob("*.json"):
                try:
                    path.unlink()
                except OSError:
                    pass
