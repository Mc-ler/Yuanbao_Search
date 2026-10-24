import asyncio

from claimlab.contracts import Evidence, VerificationUnit
from claimlab.skills.advisory import build_advisories


class StubLLM:
    def __init__(self):
        self.calls = []

    async def json(self, task, payload, system_prompt="", model=None, images=None):
        self.calls.append((task, payload))
        return {"items": [{"unit_id": "u1", "text": "可能未被索引", "confidence": "low", "caveats": "非判定"}]}


def unit(verdict="insufficient"):
    return VerificationUnit(
        unit_id="u1",
        assertion={"text": "某说法", "field": "unknown"},
        verdict=verdict,
        rule_id="R5",
        evidence=[Evidence(evidence_id="e1", url="https://a", grade="C", relation="unrelated")],
    )


def test_advisory_only_for_insufficient():
    llm = StubLLM()
    result = asyncio.run(build_advisories(llm, [unit("insufficient")]))
    assert result["u1"]["text"] == "可能未被索引"
    assert llm.calls and llm.calls[0][0] == "advisory"
    assert asyncio.run(build_advisories(llm, [unit("conflict")])) == {}


def test_llm_messages_include_image():
    from claimlab.llm.client import OpenAICompatLLM

    messages = OpenAICompatLLM._messages({"q": 1}, "sys", [{"n": 1, "data_url": "data:image/jpeg;base64,xxx"}])
    content = messages[-1]["content"]
    assert isinstance(content, list)
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg")
