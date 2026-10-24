"""Small filesystem helpers with Windows-friendly atomic writes."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path


def atomic_write_text(path: Path, text: str, retries: int = 6, delay: float = 0.06) -> None:
    """Write via a uniquely named temp file, retrying the replace on Windows locks.

    Antivirus/indexers occasionally hold a freshly created file for a few
    milliseconds; a blind os.replace then fails with WinError 5. A short
    bounded retry is enough, and the final fallback still writes the value.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
    tmp.write_text(text, encoding="utf-8")
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            os.replace(tmp, path)
            return
        except PermissionError as exc:  # WinError 5 / sharing violation
            last_error = exc
            time.sleep(delay * (attempt + 1))
    # Last resort: direct write, then clean the temp file.
    try:
        path.write_text(text, encoding="utf-8")
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
    if last_error is not None and not path.exists():
        raise last_error
