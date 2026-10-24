import asyncio

from claimlab.contracts import ResearchTask
from claimlab.skills.extraction import extract_claims, heuristic_extract


class EmptyLLM:
    async def json(self, task, payload, system_prompt="", model=None, images=None):
        return {"facts": []}


def test_history_claim_is_extracted():
    result = heuristic_extract(ResearchTask(text="西安城墙现存主体是明代修建的。"))
    assert result.facts
    assert result.facts[0].field == "general_fact"
    assert "明代" in result.facts[0].text


def test_statistic_is_not_misclassified_as_price():
    result = heuristic_extract(ResearchTask(text="2024年全国居民人均可支配收入为41314元。"))
    assert result.facts
    assert result.facts[0].field == "general_fact"
    assert all(fact.field != "price" for fact in result.facts)


def test_question_has_actionable_reason():
    result = heuristic_extract(ResearchTask(text="西安城墙现存主体是什么年代修建的？"))
    assert result.facts == []
    assert result.input_kind == "question"
    assert result.reason == "open_question_needs_research"
    assert result.guidance


def test_yes_no_question_is_rewritten():
    result = heuristic_extract(ResearchTask(text="西安城墙现存主体是否是明代修建的？"))
    assert result.facts
    assert result.input_kind == "question_rewritten"
    assert "明代" in result.facts[0].text


def test_pure_opinion_is_not_a_fact():
    result = heuristic_extract(ResearchTask(text="这家店太难吃了。"))
    assert result.facts == []
    assert result.input_kind == "opinion"
    assert result.emotions


def test_empty_llm_falls_back_to_general_claim():
    result = asyncio.run(extract_claims(EmptyLLM(), ResearchTask(text="西安城墙现存主体是明代修建的。")))
    assert result.facts
    assert result.facts[0].field == "general_fact"
