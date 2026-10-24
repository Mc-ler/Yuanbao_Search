from claimlab.contracts import Claim, Evidence
from claimlab.skills.judging import judge_unit, specificity


def claim(text="人均68元", field="price", value=68) -> Claim:
    return Claim(claim_id="c1", type="fact", text=text, field=field, value=value)


def ev(grade="A", relation="support", cluster="c1", size=1, domains=None, observed=None, quote="quote") -> Evidence:
    return Evidence(
        evidence_id=f"{grade}-{cluster}-{relation}-{observed}",
        grade=grade,
        relation=relation,
        cluster_id=cluster,
        cluster_size=size,
        cluster_domains=domains or ["a.gov.cn"],
        observed_value=observed,
        quote=quote,
        url="https://a.gov.cn/x",
    )


def test_r1_a_refute_wins():
    unit = judge_unit(claim(), [ev("A", "refute"), ev("B", "support", "c2")])
    assert unit.verdict == "refuted" and unit.rule_id == "R1"


def test_r2_a_support():
    unit = judge_unit(claim(), [ev("A", "support")])
    assert unit.verdict == "established" and unit.rule_id == "R2"


def test_r2b_two_b_clusters():
    unit = judge_unit(claim(), [ev("B", "support", "c1"), ev("B", "support", "c2")])
    assert unit.verdict == "established" and unit.rule_id == "R2b"


def test_r3_b_support_and_refute():
    unit = judge_unit(claim(), [ev("B", "support", "c1"), ev("B", "refute", "c2")])
    assert unit.verdict == "conflict" and unit.rule_id == "R3"


def test_r3_a_support_and_refute():
    unit = judge_unit(claim(), [ev("A", "support", "c1"), ev("A", "refute", "c2")])
    assert unit.verdict == "conflict" and unit.rule_id == "R3"


def test_r3_conflicting_values():
    unit = judge_unit(
        claim(),
        [
            ev("B", "support", "c1", observed="68", quote="人均68元"),
            ev("B", "support", "c2", observed="120", quote="人均120元"),
        ],
    )
    assert unit.verdict == "conflict" and unit.rule_id == "R3"


def test_r4_vague_repost_cluster():
    vague = claim("这家店很值得去", field="unknown", value=None)
    text = "这家店很值得去"
    unit = judge_unit(
        vague,
        [
            ev("D", "support", "c1", size=3, domains=["a.com", "b.com", "c.com"], quote=text),
            ev("D", "support", "c1", size=3, domains=["a.com", "b.com", "c.com"], quote=text),
            ev("D", "support", "c1", size=3, domains=["a.com", "b.com", "c.com"], quote=text),
        ],
        {"pages_count": 3, "queries_count": 2},
    )
    assert unit.verdict == "suspect" and unit.rule_id == "R4"


def test_r5_empty_is_insufficient():
    unit = judge_unit(claim(), [], {"pages_count": 0, "queries_count": 3})
    assert unit.verdict == "insufficient" and unit.rule_id == "R5"
    assert unit.failure_type == "not_indexed"


def test_layered_a_only_differs():
    unit = judge_unit(claim(), [ev("A", "support"), ev("B", "refute", "c2")])
    assert unit.verdict == "conflict"
    assert unit.layered.a_level_only == "established"


def test_cluster_votes_count_once():
    unit = judge_unit(
        claim(),
        [
            ev("B", "support", "c1", size=3),
            ev("B", "support", "c1", size=3),
            ev("B", "support", "c1", size=3),
        ],
    )
    assert unit.cluster_votes.support == 1
    assert "同源" in unit.cluster_votes.note


def test_specificity_counts_categories():
    count, categories = specificity("人均68元，周一闭店，地址在钟楼附近3号")
    assert count >= 3
    assert "price" in categories
