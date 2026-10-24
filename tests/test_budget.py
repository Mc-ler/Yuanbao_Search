import pytest

from claimlab.search.budget import Budget, BudgetExceeded


def test_assertion_limit(tmp_path):
    budget = Budget(tmp_path, max_per_assertion=2, max_per_run=10, max_per_day=100)
    budget.charge("c1")
    budget.charge("c1")
    with pytest.raises(BudgetExceeded):
        budget.charge("c1")
    assert budget.calls == 2


def test_run_limit(tmp_path):
    budget = Budget(tmp_path, max_per_assertion=10, max_per_run=2, max_per_day=100)
    budget.charge("c1")
    budget.charge("c2")
    with pytest.raises(BudgetExceeded):
        budget.charge("c3")
    assert budget.calls == 2


def test_cache_hit_not_charged(tmp_path):
    budget = Budget(tmp_path, max_per_assertion=1, max_per_run=1, max_per_day=100)
    budget.charge("c1")
    budget.hit()
    assert budget.summary()["calls"] == 1
    assert budget.summary()["cache_hits"] == 1


def test_daily_limit_persists(tmp_path):
    first = Budget(tmp_path, max_per_assertion=10, max_per_run=10, max_per_day=2)
    first.charge("c1")
    first.charge("c2")
    second = Budget(tmp_path, max_per_assertion=10, max_per_run=10, max_per_day=2)
    with pytest.raises(BudgetExceeded):
        second.charge("c3")
