"""Small .env helpers shared by the Web configuration endpoints.

Only KEY=VALUE lines are handled. Writes are atomic and preserve comments;
duplicate keys keep the last value. No values are logged.
"""

from __future__ import annotations

from pathlib import Path

from .fsutil import atomic_write_text


def read_env(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def upsert(lines: list[str], key: str, value: str) -> list[str]:
    for index, raw in enumerate(lines):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.split("=", 1)[0].strip().lower() == key.lower():
            lines[index] = f"{key}={value}"
            return lines
    lines.append(f"{key}={value}")
    return lines


def dedupe(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for line in reversed(lines):
        stripped = line.strip()
        name = ""
        if stripped and not stripped.startswith("#") and "=" in stripped:
            name = stripped.split("=", 1)[0].strip().lower()
        if name and name in seen:
            continue
        if name:
            seen.add(name)
        result.append(line)
    result.reverse()
    return result


def write_env(path: Path, lines: list[str]) -> None:
    atomic_write_text(path, "\n".join(dedupe(lines)).rstrip() + "\n")
