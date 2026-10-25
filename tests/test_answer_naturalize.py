"""User-facing answer text must not expose internal time fields."""

import asyncio

from claimlab.skills.answer import _naturalize_time_text, build_answer


def test_naturalize_time_fields():
    text = "。；as_of 为 2026-10-25；距 as_of 86 天，stale=false，非时效敏感问题。"
    cleaned = _naturalize_time_text(text)
    assert "as_of" not in cleaned
    assert "stale" not in cleaned
    assert "截至 2026年10月25日" in cleaned
    assert "距当前日期 86 天" in cleaned


def test_naturalize_leaked_dict():
    cleaned = _naturalize_time_text(
        '{"as_of": "2026-10-25", "stale": false, "time_sensitive": false, "freshness_days": 31}'
    )
    assert "{" not in cleaned and "}" not in cleaned
    assert '"' not in cleaned
    assert "截至 2026年10月25日" in cleaned
    assert "时效窗口为 31 天" in cleaned


class FakeLLM:
    async def json(self, task, payload, system_prompt="", model=None, images=None):
        return {
            "text": "结论 [1]。",
            "uncertainty": "无法确定。",
            "time_note": "as_of 为 2026-10-25；stale=false",
            "claims": [],
        }


def test_build_answer_sanitizes_uncertainty():
    rows = [
        {
            "tier": "A/B",
            "top_sources": [
                {
                    "url": "https://www.gov.cn/a",
                    "title": "来源",
                    "domain": "www.gov.cn",
                    "grade": "A",
                    "date": "2026-07-31",
                    "content_excerpt": "来源内容。",
                }
            ],
        }
    ]
    answer = asyncio.run(build_answer(FakeLLM(), "问题", rows, as_of="2026-10-25"))
    assert answer["engine"] == "llm"
    assert "as_of" not in answer["uncertainty"]
    assert "stale" not in answer["uncertainty"]
    assert "。；" not in answer["uncertainty"]
    assert "截至 2026年10月25日" in answer["uncertainty"]
