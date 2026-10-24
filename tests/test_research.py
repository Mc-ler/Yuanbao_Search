import asyncio
from pathlib import Path

from claimlab.config import Settings
from claimlab.llm.client import FakeLLM
from claimlab.research import run_research
from claimlab.runtime import Sandbox
from claimlab.search.fake import FakeSearchProvider

PAGES = [
    {
        "_triggers": ["西安城墙"],
        "title": "西安城墙历史沿革",
        "url": "https://www.stats.gov.cn/a",
        "date": "2025-01-01",
        "passage": "西安城墙现存主体为明代修建，历史沿革悠久。",
        "content": "西安城墙现存主体为明代修建，历史沿革悠久。",
    },
    {
        "_triggers": ["西安城墙"],
        "title": "西安城墙历史沿革（转载）",
        "url": "https://www.gov.cn/b",
        "date": "2025-02-01",
        "passage": "西安城墙现存主体为明代修建，历史沿革悠久。",
        "content": "西安城墙现存主体为明代修建，历史沿革悠久。",
    },
]


def make_sandbox(tmp_path: Path) -> Sandbox:
    settings = Settings(
        search_provider="fake",
        search_api_key="",
        llm_api_key="",
        allow_fake_search=True,
        screenshot_enabled=False,
        root=Path(".").resolve(),
        cache_dir=tmp_path / "cache",
        archive_dir=tmp_path / "archive",
        state_dir=tmp_path / "state",
        config_dir=Path("config"),
        fixtures_dir=Path("fixtures"),
        web_dir=Path("web"),
    )
    settings.ensure_dirs()
    return Sandbox(settings, {"fake": FakeSearchProvider(PAGES)}, {}, FakeLLM())


def test_deep_research_dedupes_and_does_not_persist(tmp_path, monkeypatch):
    sandbox = make_sandbox(tmp_path)
    called = []
    monkeypatch.setattr(sandbox.store, "upsert_run", lambda *args, **kwargs: called.append("run"))
    monkeypatch.setattr(sandbox.store, "upsert_sources", lambda *args, **kwargs: called.append("sources"))

    async def run():
        result = await run_research(sandbox, "西安城墙现存主体是什么年代修建的？")
        await sandbox.close()
        return result

    result = asyncio.run(run())
    metrics = result["metrics"]
    assert metrics["metrics_version"] == 3
    assert metrics["queries"] >= 5
    assert metrics["pages_raw"] > metrics["pages_unique"]
    assert metrics["ab_source_rate"] <= 1.0
    assert sum(metrics["grade_counts"].values()) == metrics["relevant_unique"]
    assert metrics["duplicates_removed"] >= 1
    assert metrics["pages_unique"] == len(result["source_ledger"][0]["sources"]) or metrics["pages_unique"] >= 1
    citation_urls = [item["url"] for item in result["answer"]["citations"]]
    assert len(citation_urls) == len(set(citation_urls))
    assert called == []
    assert result["report"]["kind"] == "research"
    assert result["answer"]["engine"] == "rule"
    assert "passage" not in result["answer"]["text"]


def test_deep_research_uses_focus_not_subject(tmp_path):
    sandbox = make_sandbox(tmp_path)

    async def run():
        result = await run_research(sandbox, "西安城墙现存主体是什么年代修建的？")
        await sandbox.close()
        return result

    result = asyncio.run(run())
    queries = " ".join(item.query for item in result["queries"])
    assert "西安城墙" in queries
    assert "subject" not in queries and "city" not in queries
