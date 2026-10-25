"""Assemble the deep-research report (research summary + source ledger).

The report is intentionally not a verdict: it presents the cited summary,
source ledger, metrics and evidence gaps. R1-R5 verdicts belong to the claim
board and its own report.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

DISCLAIMER = "本报告只核对公开信息与来源，不评价个人，不构成消费或法律建议。"


def build_research_report(
    question: str,
    source_ledger: list[dict[str, Any]],
    answer: dict[str, Any],
    metrics: dict[str, Any],
    *,
    gaps: list[dict[str, Any]] | None = None,
    degraded: dict[str, Any] | None = None,
) -> dict[str, Any]:
    answer = answer or {}
    return {
        "kind": "research",
        "title": "研究报告",
        "question": question,
        "summary": answer.get("text") or answer.get("answer") or "",
        "engine": answer.get("engine") or "",
        "uncertainty": answer.get("uncertainty") or "",
        "claims": answer.get("claims") or [],
        "as_of": answer.get("as_of") or "",
        "time_sensitive": bool(answer.get("time_sensitive")),
        "time_context": answer.get("time_context") or {},
        "citations": answer.get("citations") or [],
        "citation_issues": answer.get("citation_issues") or [],
        "screenshots": answer.get("screenshots") or [],
        "source_ledger": source_ledger or [],
        "metrics": metrics or {},
        "gaps": gaps or [],
        "degraded": degraded or {},
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "disclaimer": DISCLAIMER,
    }


def render_research_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = [f"# {report.get('title', '研究报告')}", ""]
    lines.append(f"> 问题：{report.get('question', '')}")
    lines.append(f"> 生成：{report.get('generated_at', '')}")
    reasons = (report.get("degraded") or {}).get("reasons") or []
    if reasons:
        lines.append("> 降级：" + "；".join(str(item) for item in reasons))
    if report.get("as_of"):
        lines.append(f"> 截止：{report.get('as_of')}（Asia/Shanghai）")
    summary = report.get("summary")
    if summary:
        lines.append("")
        lines.append("## 研究综述")
        lines.append(str(summary))
    claims = report.get("claims") or []
    if claims:
        lines.append("")
        lines.append("## 结论与证据")
        for claim in claims:
            ids = "".join(f"[{n}]" for n in claim.get("source_ids") or [])
            lines.append(f"- {claim.get('text') or ''} {ids}")
            if claim.get("quote"):
                lines.append(f"  > {claim.get('quote')}（{claim.get('source_date') or '日期未知'}）")
        lines.append("")
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
    lines.append("## 来源分册")
    for entry in report.get("source_ledger") or []:
        lines.append(f"### {entry.get('field_label') or entry.get('field') or '综合'} · {entry.get('tier') or 'insufficient'}")
        if entry.get("text"):
            lines.append(str(entry["text"]))
        for source in entry.get("sources") or []:
            lines.append(
                f"- [{source.get('n') or '?'}] ({source.get('grade') or '?'}) "
                f"{source.get('title') or source.get('domain')} ({source.get('url') or ''})"
            )
        lines.append("")
    gaps = report.get("gaps") or []
    if gaps:
        lines.append("## 证据缺口")
        for gap in gaps:
            lines.append(f"- {gap.get('field_label') or gap.get('field') or '综合'}：{gap.get('text') or ''}（{gap.get('tier')}）")
        lines.append("")
    lines.append("## 指标")
    m = report.get("metrics") or {}
    lines.append(
        f"需求 {m.get('requirements_with_ab', 0)}/{m.get('requirements', 0)} 有 A/B 来源 · "
        f"A/B 来源占比 {round((m.get('ab_source_rate') or 0) * 100, 1)}% · "
        f"去重 {m.get('duplicates_removed', 0)} 条 · 截图 {m.get('screenshots', 0)} 张"
    )
    lines.append("")
    issues = report.get("citation_issues") or []
    if issues:
        lines.append("## 引用校验")
        for issue in issues:
            lines.append(f"- [n={issue.get('n')}] {issue.get('reason')}")
        lines.append("")
    lines.append(report.get("disclaimer", ""))
    return "\n".join(lines)
