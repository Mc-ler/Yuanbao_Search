"""Search and model call budgets with a persisted daily counter.

The quota is real money: a runaway loop must be impossible to trigger by
prompting alone. Every provider call charges a budget before it leaves the
process; cache hits are counted separately and never charged.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from ..contracts import CST
from ..fsutil import atomic_write_text


class BudgetExceeded(RuntimeError):
    def __init__(self, reason: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.details = details or {}


class Budget:
    def __init__(
        self,
        state_dir: Path,
        max_per_assertion: int = 4,
        max_per_run: int = 28,
        max_per_day: int = 400,
        wall_seconds: int = 90,
    ) -> None:
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.max_per_assertion = max_per_assertion
        self.max_per_run = max_per_run
        self.max_per_day = max_per_day
        self.wall_seconds = wall_seconds
        self.calls = 0
        self.cache_hits = 0
        self.per_assertion: dict[str, int] = {}
        self.started_at = time.monotonic()
        self.stop_reason = ""
        self._day_key = datetime.now(CST).strftime("%Y-%m-%d")
        self._daily_path = self.state_dir / f"budget-{self._day_key}.json"
        self._daily_calls = self._load_daily()

    def _load_daily(self) -> int:
        if not self._daily_path.exists():
            return 0
        try:
            data = json.loads(self._daily_path.read_text(encoding="utf-8"))
            return int(data.get("calls", 0))
        except (OSError, ValueError, TypeError):
            return 0

    def _save_daily(self) -> None:
        payload = {"date": self._day_key, "calls": self._daily_calls}
        atomic_write_text(self._daily_path, json.dumps(payload))

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.started_at

    @property
    def wall_exceeded(self) -> bool:
        return self.elapsed_seconds > self.wall_seconds

    def _check_wall(self) -> None:
        if self.wall_exceeded:
            self.stop_reason = "wall_time"
            raise BudgetExceeded("wall_time", {"elapsed": round(self.elapsed_seconds, 1)})

    def charge(self, assertion_id: str = "_") -> None:
        self._check_wall()
        if self.calls >= self.max_per_run:
            self.stop_reason = "run_budget"
            raise BudgetExceeded("run_budget", {"calls": self.calls})
        if self._daily_calls >= self.max_per_day:
            self.stop_reason = "daily_budget"
            raise BudgetExceeded("daily_budget", {"daily_calls": self._daily_calls})
        used = self.per_assertion.get(assertion_id, 0)
        if used >= self.max_per_assertion:
            self.stop_reason = "assertion_budget"
            raise BudgetExceeded("assertion_budget", {"assertion_id": assertion_id, "calls": used})
        self.calls += 1
        self._daily_calls += 1
        self.per_assertion[assertion_id] = used + 1
        self._save_daily()

    def hit(self) -> None:
        self.cache_hits += 1

    def remaining_for(self, assertion_id: str) -> int:
        return max(0, self.max_per_assertion - self.per_assertion.get(assertion_id, 0))

    def remaining_run(self) -> int:
        return max(0, self.max_per_run - self.calls)

    def can_call(self, assertion_id: str = "_") -> bool:
        return (
            not self.wall_exceeded
            and self.calls < self.max_per_run
            and self._daily_calls < self.max_per_day
            and self.per_assertion.get(assertion_id, 0) < self.max_per_assertion
        )

    def summary(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "cache_hits": self.cache_hits,
            "daily_calls": self._daily_calls,
            "per_assertion": dict(self.per_assertion),
            "max_per_assertion": self.max_per_assertion,
            "max_per_run": self.max_per_run,
            "max_per_day": self.max_per_day,
            "wall_seconds": self.wall_seconds,
            "elapsed_seconds": round(self.elapsed_seconds, 2),
            "stop_reason": self.stop_reason,
        }
