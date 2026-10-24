"""Assemble the research investigation report (调查报告).

Combines the cited answer, per-field sources and metrics into one document
shared by the terminal CLI (--report) and the web UI (报告 button).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

DISCLAIMER = "本报告只核对公开信息与来源，不评价个人，不构成消费或法律建议。"


def build_research_report(
    question: str,
    rows: list[dict[str, Any]],
    answer: dict[str, Any],
    metrics: dict[str, Any],
) -> dict[str, Any]:
    fields = [
        {
            "field": row.get("field") or "",
            "text": row.get("text") or row.get("field") or "",
            "tier": row.get("tier") or "",
            "pages": row.get("pages") or 0,
            "relevant_pages": row.get("relevant_pages") or 0,
            "top_sources": row.get("top_sources") or [],
        }
        for row in (rows or [])
    ]
    answer = answer or {}
    return {
        "title": "调查报告",
        "question": question,
        "answer": answer.get("answer") or "",
        "verdict": answer.get("verdict") or "",
        "uncertainty": answer.get("uncertainty") or "",
        "engine": answer.get("engine") or "",
        "citations": answer.get("citations") or [],
        "fields": fields,
        "metrics": metrics or {},
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "disclaimer": DISCLAIMER,
    }


def render_research_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = [f"# {report.get('title', '调查报告')}", ""]
    lines.append(f"> 问题：{report.get('question', '')}")
    lines.append(f"> 生成：{report.get('generated_at', '')}")
    verdict = report.get("verdict")
    if verdict:
        lines.append("")
        lines.append(f"**结论**：{verdict}")
    answer = report.get("answer")
    if answer:
        lines.append("")
        lines.append("## 结论与依据")
        lines.append(str(answer))
    citations = report.get("citations") or []
    if citations:
        lines.append("")
        lines.append("## 引用来源")
        for c in citations:
            lines.append(
                f"- [{c.get('n')}] ({c.get('grade') or '?'}) {c.get('title') or c.get('domain')}"
                f" — {c.get('domain') or ''} {c.get('date') or ''} {c.get('url') or ''}"
            )
    lines.append("")
    lines.append("## 字段来源")
    for f in report.get("fields") or []:
        lines.append(f"### {f.get('field') or 'unknown'} · {f.get('tier') or 'insufficient'}")
        if f.get("text"):
            lines.append(str(f["text"]))
        for s in f.get("top_sources") or []:
            lines.append(f"- [{s.get('grade') or '?'}] {s.get('title') or s.get('domain')} ({s.get('url') or ''})")
        lines.append("")
    lines.append("## 指标")
    m = report.get("metrics") or {}
    lines.append(
        f"字段 {m.get('fields_with_ab', 0)}/{m.get('fields', 0)} · "
        f"相关官方率 {round((m.get('relevant_official_rate') or 0) * 100, 1)}% · "
        f"零结果 {m.get('zero_requirements', 0)}"
    )
    lines.append("")
    lines.append(report.get("disclaimer", ""))
    return "\n".join(lines)
