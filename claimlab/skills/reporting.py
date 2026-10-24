"""Assemble contract C (research report) from verification units."""

from __future__ import annotations

from typing import Any

from ..contracts import (
    ClusterVotes,
    ExtractionResult,
    ReportStats,
    ResearchReport,
    ResearchTask,
    Round,
    VerificationUnit,
    jsonable,
)


def _conflict_view(unit: VerificationUnit) -> dict[str, Any]:
    support = [item for item in unit.evidence if item.relation == "support"]
    refute = [item for item in unit.evidence if item.relation == "refute"]
    return {
        "unit_id": unit.unit_id,
        "assertion": unit.assertion,
        "support": [
            {"grade": item.grade, "site": item.site, "date": item.date, "url": item.url, "quote": item.quote}
            for item in support[:3]
        ],
        "refute": [
            {"grade": item.grade, "site": item.site, "date": item.date, "url": item.url, "quote": item.quote}
            for item in refute[:3]
        ],
        "layered": {
            "all_evidence": unit.layered.all_evidence,
            "a_level_only": unit.layered.a_level_only,
        },
        "cluster_note": unit.cluster_votes.note,
    }


def build_report(
    task: ResearchTask,
    extraction: ExtractionResult,
    units: list[VerificationUnit],
    rounds: list[Round],
    trace: list[dict[str, Any]],
    stats: ReportStats,
) -> ResearchReport:
    conflicts = [_conflict_view(unit) for unit in units if unit.verdict == "conflict"]
    unverified: list[str] = []
    for unit in units:
        if unit.verdict in {"insufficient", "suspect"}:
            unverified.extend(unit.unverified or [unit.assertion.get("text", "")])
    citations = sorted({item.url for unit in units for item in unit.evidence if item.url})
    counts: dict[str, int] = {}
    for unit in units:
        counts[unit.verdict] = counts.get(unit.verdict, 0) + 1
    verdicts = set(counts)
    if not units:
        overall = "no_claim"
    elif verdicts == {"established"}:
        overall = "all_established"
    elif verdicts == {"refuted"}:
        overall = "all_refuted"
    elif not verdicts - {"insufficient", "suspect"}:
        overall = "insufficient"
    elif verdicts & {"established", "refuted", "conflict"}:
        overall = "mixed"
    else:
        overall = "partial"
    aggregate = {"overall": overall, "counts": counts, "units": len(units)}
    return ResearchReport(
        task=task,
        profile=extraction.profile,
        units=list(units),
        rounds=list(rounds),
        trace=list(trace),
        stats=stats,
        conflicts=conflicts,
        unverified=list(dict.fromkeys(unverified)),
        citations=citations,
        aggregate=aggregate,
        guidance=extraction.guidance,
    )


def report_to_dict(report: ResearchReport) -> dict[str, Any]:
    return jsonable(report)


def render_markdown(report: ResearchReport) -> str:
    lines: list[str] = []
    title = next((unit.assertion.get("text", "") for unit in report.units if unit.assertion.get("text")), "")
    lines.append(f"# {title[:60] or '一句话查证报告'}")
    lines.append("")
    lines.append(f"> 输入：{report.task.text[:160]}")
    lines.append(f"> 生成：{report.generated_at}")
    lines.append("")
    if report.aggregate:
        lines.append("> 汇总：" + str(report.aggregate.get("overall", "")) + " · " + str(report.aggregate.get("counts", {})))
        lines.append("")
    if report.guidance:
        lines.append(f"> 提示：{report.guidance}")
        lines.append("")
    profile = report.profile
    lines.append(
        f"**画像**：事实 {profile.get('facts', 0)} · 情绪 {profile.get('emotions', 0)} · "
        f"{profile.get('quadrant', '')} · 关切：{', '.join(profile.get('concerns', [])) or '无'}"
    )
    lines.append("")
    for unit in report.units:
        assertion = unit.assertion
        lines.append(f"## {assertion.get('text', '')}")
        lines.append(
            f"- 判定：**{unit.verdict}**（{unit.rule_id}）；只看 A 级：{unit.layered.a_level_only}"
        )
        lines.append(f"- 行动含义：{unit.action}")
        if unit.cluster_votes.note:
            lines.append(f"- 计票：{unit.cluster_votes.note}")
        if unit.advisory:
            lines.append(f"- 模型参考意见（非判定）：{unit.advisory.get('text', '')}")
        for item in unit.evidence:
            if item.relation == "unrelated":
                continue
            lines.append(
                f"  - [{item.grade}] {item.site or item.domain} · {item.date or '日期未知'} · "
                f"{item.relation} · {item.url}"
            )
            if item.quote:
                lines.append(f"    > {item.quote[:160]}")
        lines.append("")
    lines.append("## 统计")
    stats = report.stats
    lines.append(
        f"检索 {stats.calls} 次 · 缓存 {stats.cache_hits} 次 · 命中 {stats.results} 条 · "
        f"合成 {stats.clusters} 个簇 · A 级 {stats.a_level} 条"
    )
    lines.append("")
    lines.append(report.disclaimer)
    return "\n".join(lines)
