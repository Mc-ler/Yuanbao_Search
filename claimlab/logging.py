"""Small, safe logging setup for local runs and probes.

All log files are local and gitignored. Never log API keys, Authorization headers,
.env contents, or full raw response bodies. Query text and source domains are
allowed because they are required to debug source quality.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(
    log_dir: Path,
    filename: str,
    level: str = "INFO",
    max_bytes: int = 5_000_000,
    backup_count: int = 5,
) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / filename
    logger = logging.getLogger("claimlab")
    logger.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    logger.propagate = False
    for handler in logger.handlers:
        if getattr(handler, "_claimlab_path", None) == str(path):
            return path
    handler = RotatingFileHandler(
        path,
        maxBytes=max(1024, int(max_bytes)),
        backupCount=max(1, int(backup_count)),
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    handler._claimlab_path = str(path)  # type: ignore[attr-defined]
    logger.addHandler(handler)
    return path


def event(logger: logging.Logger, name: str, level: int = logging.INFO, **fields: Any) -> None:
    parts: list[str] = [f"event={name}"]
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            value = ",".join(str(item) for item in value)
        text = str(value).replace("\n", " ").replace("\r", " ")
        parts.append(f"{key}={text}")
    logger.log(level, " ".join(parts))
