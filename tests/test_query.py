from claimlab.contracts import Claim
from claimlab.skills.query import plan_key, plan_queries


def price_claim() -> Claim:
    return Claim(claim_id="c1", type="fact", text="人均68元", field="price", value=68)


def test_plan_has_precise_and_is_bounded():
    plans = plan_queries(price_claim(), focus="示例泡馍")
    assert 2 <= len(plans) <= 4
    assert any(plan.precision == "precise" for plan in plans)
    assert all(plan.query for plan in plans)
    keys = [(plan.query, plan.site, plan.industry) for plan in plans]
    assert len(keys) == len(set(keys))


def test_retry_changes_strategy_and_avoids_used():
    first = plan_queries(price_claim(), focus="示例泡馍", round_no=0)
    used = {plan_key(plan) for plan in first}
    retry = plan_queries(price_claim(), focus="示例泡馍", round_no=1, used=used)
    assert retry
    assert all(plan_key(plan) not in used for plan in retry)
    assert any(plan.precision == "precise" for plan in retry)


def test_unknown_field_still_plans():
    claim = Claim(claim_id="c2", type="fact", text="这家店开了二十年", field="unknown")
    plans = plan_queries(claim, focus="示例小店")
    assert plans
    assert any(plan.precision == "precise" for plan in plans)
