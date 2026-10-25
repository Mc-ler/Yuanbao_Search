"""Aggregate summary must be natural language, never a counts dict."""

from claimlab.contracts import ReportStats, ResearchReport, ResearchTask, VerificationUnit
from claimlab.skills.reporting import aggregate_summary, render_markdown


def test_aggregate_summary_for_refuted_and_suspect():
    assert aggregate_summary("mixed", {"refuted": 2, "suspect": 1}) == "共 3 条断言：2 条不成立、1 条存疑。"


def test_aggregate_summary_for_all_refuted():
    assert aggregate_summary("all_refuted", {"refuted": 2}) == "共 2 条断言：全部不成立。"


def test_aggregate_summary_for_no_units():
    assert "未拆出" in aggregate_summary("no_claim", {})


def test_markdown_does_not_expose_counts_dict():
    unit = VerificationUnit(
        unit_id="u1",
        assertion={"text": "示例断言", "field": "general_fact"},
        verdict="refuted",
        rule_id="R1",
    )
    report = ResearchReport(
        task=ResearchTask(text="示例断言"),
        units=[unit],
        stats=ReportStats(),
        aggregate={
            "overall": "mixed",
            "overall_label": "结论混合",
            "counts": {"refuted": 1},
            "summary": aggregate_summary("mixed", {"refuted": 1}),
            "units": 1,
        },
    )
    md = render_markdown(report)
    assert '{"refuted"' not in md
    assert "1 条不成立" in md
