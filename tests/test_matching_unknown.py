"""Unknown fields are "not judged", not "unrelated"."""

from claimlab.contracts import Claim, Evidence, SearchPage
from claimlab.skills.judging import judge_unit
from claimlab.skills.matching import heuristic_match


def page() -> SearchPage:
    return SearchPage(
        title="西安城墙",
        url="https://www.xa.gov.cn/a",
        domain="www.xa.gov.cn",
        passage="现存城墙建于明洪武七年到十一年(1374-1378)。",
    )


def claim(field: str = "scenic_history") -> Claim:
    return Claim(
        claim_id="c1",
        type="fact",
        text="西安城墙现存主体是明代修建的。",
        field=field,
        value="明代",
    )


def test_non_legacy_heuristic_is_unknown():
    result = heuristic_match(claim(), page())
    assert result.relation == "unknown"


def test_unknown_does_not_become_evidence_or_votes():
    evidence = Evidence(
        evidence_id="e1",
        grade="A",
        relation="unknown",
        url="https://www.xa.gov.cn/a",
    )
    unit = judge_unit(claim(), [evidence], {"pages_count": 1, "queries_count": 1})
    assert unit.verdict == "insufficient"
    assert unit.rule_id == "R5"
    assert unit.cluster_votes.support == 0
    assert unit.cluster_votes.refute == 0


def test_legacy_heuristic_still_returns_unrelated_for_mismatch():
    result = heuristic_match(claim("address"), page())
    assert result.relation == "unrelated"
