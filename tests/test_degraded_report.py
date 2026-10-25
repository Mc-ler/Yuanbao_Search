"""Degraded metadata is carried into reports and markdown."""

from claimlab.skills.research_report import build_research_report, render_research_markdown


def test_research_report_carries_degraded_reasons():
    answer = {"text": "结论 [1]", "engine": "rule", "degraded_reason": "no_valid_citation", "citations": []}
    metrics = {"requirements": 1}
    report = build_research_report(
        "问题",
        [],
        answer,
        metrics,
        degraded={"reasons": ["answer=rule (no_valid_citation)"], "answer_engine": "rule"},
    )
    assert report["degraded"]["reasons"]
    md = render_research_markdown(report)
    assert "降级" in md
    assert "no_valid_citation" in md
