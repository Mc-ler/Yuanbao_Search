"""Fixture loading (contract A)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config import FIXTURES_DIR
from ..contracts import ResearchTask


def load_fixture(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"fixture must be an object: {path}")
    return data


def load_all_fixtures(directory: Path | None = None) -> dict[str, dict[str, Any]]:
    root = directory or FIXTURES_DIR
    fixtures: dict[str, dict[str, Any]] = {}
    for path in sorted(root.glob("*.json")):
        try:
            data = load_fixture(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        fixture_id = str(data.get("fixture_id") or path.stem)
        data["_path"] = str(path)
        fixtures[fixture_id] = data
    return fixtures


def fixture_task(fixture: dict[str, Any]) -> ResearchTask:
    return ResearchTask(
        text=str(fixture.get("text") or ""),
        mode=str(fixture.get("mode") or "verify_claim"),  # type: ignore[arg-type]
        subject=fixture.get("subject"),
        city=fixture.get("city"),
        fixture_id=fixture.get("fixture_id"),
    )


def fixture_pages(fixtures: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    pages: list[dict[str, Any]] = []
    for fixture in fixtures.values():
        pages.extend(fixture.get("mock_pages") or [])
    return pages


def fixture_public_list(fixtures: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "fixture_id": fixture.get("fixture_id"),
            "title": fixture.get("title"),
            "text": fixture.get("text"),
            "subject": fixture.get("subject"),
            "city": fixture.get("city"),
            "expected": fixture.get("expected"),
        }
        for fixture in fixtures.values()
    ]
