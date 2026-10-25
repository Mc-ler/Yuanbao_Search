import pytest

from claimlab.llm.client import LLMError, _coerce_content


def test_answer_prose_is_preserved_when_json_is_missing():
    parsed = _coerce_content("answer", "结论：无法确定 [1]。")
    assert parsed["text"].startswith("结论")
    assert parsed["citations_used"] == []
    assert "非严格 JSON" in parsed["uncertainty"]


def test_non_answer_prose_still_fails_json_contract():
    with pytest.raises(LLMError):
        _coerce_content("extract_claims", "not json")
