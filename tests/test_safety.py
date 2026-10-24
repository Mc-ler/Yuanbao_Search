import pytest

from claimlab.contracts import ResearchTask
from claimlab.skills.safety import SafetyError, check_task, lint_generated_text, mask_pii


def test_empty_rejected():
    with pytest.raises(SafetyError):
        check_task(ResearchTask(text="  "))


def test_political_topic_rejected():
    with pytest.raises(SafetyError):
        check_task(ResearchTask(text="这次选举的结果怎么样"))


def test_personal_subject_rejected():
    with pytest.raises(SafetyError):
        check_task(ResearchTask(text="某博主说这家店怎么样"))


def test_business_claim_allowed():
    check_task(ResearchTask(text="这家泡馍店人均68元"))


def test_banned_phrase_cleaned():
    cleaned, violations = lint_generated_text("这就是水军，收钱了")
    assert "水军" not in cleaned
    assert "收钱" not in cleaned
    assert violations


def test_phone_masked():
    assert "13812345678" not in mask_pii("电话 13812345678")
