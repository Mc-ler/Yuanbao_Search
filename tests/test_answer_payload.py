import asyncio
import json

from claimlab.skills.answer import NO_RESULT_TEXT, _rule_answer, build_answer, build_citations


class CaptureLLM:
    def __init__(self, text="结论 [1]"):
        self.payload = None
        self.images = None
        self.text = text

    async def json(self, task, payload, system_prompt="", model=None, images=None):
        self.payload = payload
        self.images = images
        return {"text": self.text, "citations_used": [1], "uncertainty": ""}


def rows():
    return [{
        "field": "scenic_history",
        "tier": "A/B",
        "top_sources": [{
            "grade": "A",
            "title": "来源标题",
            "domain": "gov.cn",
            "url": "https://gov.cn/x",
            "date": "2025-01-01",
            "passage": "SECRET_BODY_SHOULD_NOT_REACH_THE_MODEL",
        }],
    }]


def test_answer_payload_has_no_passage_and_uses_images():
    llm = CaptureLLM()
    images = [{"n": 1, "data_url": "data:image/jpeg;base64,xxx"}]
    result = asyncio.run(build_answer(llm, "问题", rows(), images=images, screenshots={1: {"url": "/api/evidence/r/1", "captured": True}}))
    assert result["engine"] == "llm"
    assert "SECRET_BODY" not in json.dumps(llm.payload, ensure_ascii=False)
    assert llm.images == images
    assert result["citations"][0]["screenshot_url"] == "/api/evidence/r/1"


def test_invalid_only_citation_falls_back_to_rule():
    llm = CaptureLLM("没有来源的结论 [9]")
    result = asyncio.run(build_answer(llm, "问题", rows()))
    assert result["engine"] == "rule"
    assert any(item["reason"] == "no_valid_citation" for item in result["citation_issues"])


def test_no_sources_returns_explicit_unknown():
    result = asyncio.run(build_answer(None, "问题", []))
    assert result["engine"] == "rule"
    assert NO_RESULT_TEXT in result["text"]


def test_rule_fallback_has_ab_source_points_not_unknown_placeholder():
    sample = rows()
    sample[0]["field_label"] = "历史沿革"
    text = _rule_answer(sample, build_citations(sample))
    assert "尚无模型综述" not in text
    assert "历史沿革" in text
    assert "来源要点" in text
    assert "unknown" not in text
