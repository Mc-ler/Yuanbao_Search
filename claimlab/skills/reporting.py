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

OVERALL_LABELS = {
    "all_established": "全部成立",
    "all_refuted": "全部不成立",
    "insufficient": "无法确定",
    "mixed": "结论混合",
    "partial": "部分可判定",
    "no_claim": "未拆出断言",
}

VERDICT_LABELS = {
    "established": "成立",
    "refuted": "不成立",
    "conflict": "结论冲突",
    "suspect": "存疑",
    "insufficient": "无法确定",
}

# A stable order makes "2 条不成立、1 条存疑" deterministic across runs.
VERDICT_ORDER = ("established", "refuted", "conflict", "suspect", "insufficient")


def aggregate_summary(overall: str, counts: dict[str, int]) -> str:
    """Human-readable aggregate; never expose the raw counts dict to users."""
    total = sum(int(counts.get(verdict, 0)) for verdict in VERDICT_ORDER)
    if total == 0:
        return OVERALL_LABELS.get(overall, "未拆出可核验断言") + "。"
    parts = [
        f"{int(counts[verdict])} 条{VERDICT_LABELS[verdict]}"
        for verdict in VERDICT_ORDER
        if int(counts.get(verdict, 0)) > 0
    ]
    if len(parts) == 1 and overall in {"all_established", "all_refuted", "insufficient"}:
        return f"共 {total} 条断言：{OVERALL_LABELS[overall]}。"
    return f"共 {total} 条断言：" + "、".join(parts) + "。"


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
    degraded: dict[str, Any] | None = None,
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
    aggregate = {
        "overall": overall,
        "overall_label": OVERALL_LABELS.get(overall, overall),
        "counts": counts,
        "summary": aggregate_summary(overall, counts),
        "units": len(units),
    }
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
        degraded=degraded or {},
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
        summary = report.aggregate.get("summary") or aggregate_summary(
            str(report.aggregate.get("overall") or ""),
            report.aggregate.get("counts") or {},
        )
        lines.append("> 汇总：" + summary)
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
            if item.relation in {"unrelated", "unknown"}:
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
    unknown = sum(1 for unit in report.units for item in unit.evidence if item.relation == "unknown")
    lines.append(
        f"检索 {stats.calls} 次 · 缓存 {stats.cache_hits} 次 · 命中 {stats.results} 条 · "
        f"合成 {stats.clusters} 个簇 · A 级 {stats.a_level} 条 · 未判定 {unknown} 条"
    )
    lines.append("")
    lines.append(report.disclaimer)
    return "\n".join(lines)
