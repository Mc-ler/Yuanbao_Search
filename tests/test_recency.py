from datetime import date

from claimlab.skills.recency import freshness_days, is_time_sensitive, sort_sources, stale_evidence


def test_time_sensitive_markers():
    assert is_time_sensitive("截至今天，最新进展是什么？")
    assert is_time_sensitive("这项新规什么时候实施？")
    assert not is_time_sensitive("什么是溯源查证？")


def test_sources_sort_newest_first_and_unknown_last():
    sources = [
        {"date": "2024-01-01", "grade": "A", "score": 0.9},
        {"date": "2026-10-20", "grade": "B", "score": 0.1},
        {"date": "", "grade": "A", "score": 0.5},
    ]
    ordered = sort_sources(sources, time_sensitive=True)
    assert ordered[0]["date"] == "2026-10-20"
    assert ordered[-1]["date"] == ""
    assert [item["date"] for item in ordered[:2]] == ["2026-10-20", "2024-01-01"]


def test_stale_evidence_detects_old_latest_source():
    context = stale_evidence(
        [{"date": "2024-01-01"}],
        "截至今天的最新消息是什么？",
        as_of=date(2026, 10, 25),
    )
    assert context["stale"] is True
    assert context["latest_source_age_days"] > context["freshness_days"]
    assert freshness_days("本周最新消息") == 7
