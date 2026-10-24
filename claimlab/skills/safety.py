"""Input/output guardrails.

Scope: consumer-facing research about businesses and public pages. No
political topics, no personal profiles, no defamatory verdicts. The guard
is intentionally conservative and explainable; it is not a classifier.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from ..config import CONFIG_DIR
from ..contracts import ResearchTask


class SafetyError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@lru_cache(maxsize=1)
def _lexicons() -> dict[str, Any]:
    return json.loads((CONFIG_DIR / "lexicons.json").read_text(encoding="utf-8"))


def check_task(task: ResearchTask) -> None:
    text = (task.text or "").strip()
    if not text:
        raise SafetyError("输入为空")
    if len(text) > 4000:
        raise SafetyError("输入过长（上限 4000 字符）")
    for term in _lexicons().get("political_terms", []):
        if term in text:
            raise SafetyError(f"该主题不在范围内（命中：{term}）；本工具只做消费/经营主体的公开说法核验")
    subject = (task.subject or "").strip()
    for marker in _lexicons().get("personal_markers", []):
        if marker in subject:
            raise SafetyError("本工具不评价个人；请给出经营主体或公开页面，而不是个人账号")


def mask_pii(text: str) -> str:
    text = re.sub(r"1[3-9]\d{9}", "1**********", text)
    text = re.sub(r"\d{17}[\dXx]", "******************", text)
    return text


def lint_generated_text(text: str) -> tuple[str, list[str]]:
    """Clean our own generated prose; never rewrite source quotes."""
    violations: list[str] = []
    result = mask_pii(text or "")
    for phrase in _lexicons().get("banned_phrases", []):
        if phrase in result:
            violations.append(phrase)
            result = result.replace(phrase, "[不当表述已移除]")
    return result, violations


def lint_report_text(report: Any) -> list[str]:
    """Collect violations from generated action strings only."""
    violations: list[str] = []
    for unit in getattr(report, "units", []) or []:
        cleaned, found = lint_generated_text(getattr(unit, "action", "") or "")
        if found:
            unit.action = cleaned
            violations.extend(found)
    return violations
