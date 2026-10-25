"""Per-task token/thinking options and citation breadth."""

from claimlab.keys import LLMProvider
from claimlab.llm.client import OpenAICompatLLM
from claimlab.skills.answer import build_citations


def provider() -> LLMProvider:
    return LLMProvider(
        name="deepseek",
        label="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        api_key="sk-test",
        thinking="disabled",
        max_tokens=4096,
        task_options={"answer": {"thinking": "auto", "max_tokens": 8192}},
    )


def test_task_params_use_answer_override():
    assert OpenAICompatLLM._task_params(provider(), "answer") == (8192, "auto")
    assert OpenAICompatLLM._task_params(provider(), "decompose_requirements") == (4096, "disabled")


def test_citations_default_keeps_all_sources():
    rows = [
        {
            "top_sources": [
                {"url": f"https://a/{index}", "title": str(index), "domain": "a", "grade": "A"}
                for index in range(6)
            ]
        }
    ]
    citations = build_citations(rows)
    assert len(citations) == 6
    assert [item["n"] for item in citations] == [1, 2, 3, 4, 5, 6]


def test_citations_explicit_limit_still_works():
    rows = [
        {
            "top_sources": [
                {"url": f"https://a/{index}", "title": str(index), "domain": "a", "grade": "A"}
                for index in range(4)
            ]
        }
    ]
    assert len(build_citations(rows, limit=2)) == 2
