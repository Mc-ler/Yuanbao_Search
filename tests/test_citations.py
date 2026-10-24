from claimlab.skills.citations import extract_refs, validate_citations


def citations():
    return [{"n": 1, "url": "https://a"}, {"n": 2, "url": "https://b"}]


def test_valid_refs_are_kept():
    text, issues = validate_citations("结论 [1]，依据 [2]。", citations())
    assert text == "结论 [1]，依据 [2]。"
    assert issues == []


def test_out_of_range_is_marked():
    text, issues = validate_citations("结论 [1]，错误 [9]。", citations())
    assert "[9?]" in text
    assert issues[0]["n"] == 9
    assert issues[0]["reason"] == "out_of_range"


def test_no_valid_citation_is_reported():
    text, issues = validate_citations("没有编号的结论。", citations())
    assert text == "没有编号的结论。"
    assert any(item["reason"] == "no_valid_citation" for item in issues)


def test_extract_refs():
    assert extract_refs("[1] [22] [x]") == [1, 22]
