"""In-memory store for evidence screenshots (never written to disk)."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class ImageRecord:
    data: bytes
    media_type: str
    created_at: float


class EvidenceImageStore:
    def __init__(self, ttl_seconds: int = 1800, max_runs: int = 20) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_runs = max_runs
        self._items: dict[str, dict[int, ImageRecord]] = {}
        self._lock = threading.Lock()

    def put(self, run_id: str, number: int, data: bytes, media_type: str = "image/jpeg") -> None:
        with self._lock:
            self._prune_locked()
            bucket = self._items.setdefault(run_id, {})
            bucket[int(number)] = ImageRecord(data=data, media_type=media_type, created_at=time.time())
            while len(self._items) > self.max_runs:
                oldest = min(self._items, key=lambda key: max(item.created_at for item in self._items[key].values()))
                self._items.pop(oldest, None)

    def get(self, run_id: str, number: int) -> ImageRecord | None:
        with self._lock:
            bucket = self._items.get(run_id)
            if not bucket:
                return None
            record = bucket.get(int(number))
            if record is None:
                return None
            if time.time() - record.created_at > self.ttl_seconds:
                bucket.pop(int(number), None)
                return None
            return record

    def _prune_locked(self) -> None:
        now = time.time()
        for run_id in list(self._items):
            bucket = self._items[run_id]
            for number in list(bucket):
                if now - bucket[number].created_at > self.ttl_seconds:
                    bucket.pop(number, None)
            if not bucket:
                self._items.pop(run_id, None)
