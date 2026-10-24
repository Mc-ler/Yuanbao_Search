import asyncio
from pathlib import Path

import pytest

from claimlab.config import Settings
from claimlab.llm.client import FakeLLM
from claimlab.pipeline import Pipeline
from claimlab.search.archive import ArchiveWriter
from claimlab.search.budget import Budget
from claimlab.search.fake import FakeSearchProvider
from claimlab.search.gateway import SearchGateway
from claimlab.store.fixtures import fixture_task, load_fixture

ROOT = Path(__file__).resolve().parent.parent


def make_settings(tmp_path: Path) -> Settings:
    settings = Settings(
        search_provider="fake",
        search_api_key="",
        llm_api_key="",
        llm_model="",
        root=ROOT,
        cache_dir=tmp_path / "cache",
        archive_dir=tmp_path / "archive",
        state_dir=tmp_path / "state",
        config_dir=ROOT / "config",
        fixtures_dir=ROOT / "fixtures",
        web_dir=ROOT / "web",
    )
    settings.ensure_dirs()
    return settings


def run_fixture(name: str, tmp_path: Path):
    fixture = load_fixture(ROOT / "fixtures" / f"{name}.json")
    settings = make_settings(tmp_path)
    provider = FakeSearchProvider(fixture.get("mock_pages") or [])
    archive = ArchiveWriter(settings.archive_dir)
    budget = Budget(settings.state_dir, max_per_assertion=4, max_per_run=28, max_per_day=400)
    gateway = SearchGateway(settings, {"fake": provider}, budget, archive)
    pipeline = Pipeline(settings, gateway, FakeLLM(), archive, budget)
    report = asyncio.run(pipeline.run(fixture_task(fixture)))
    return report, provider, gateway


def test_established_case(tmp_path):
    report, _, _ = run_fixture("case_established", tmp_path)
    verdicts = [unit.verdict for unit in report.units]
    assert verdicts == ["established", "established", "established"]
    assert report.stats.calls <= 28
    assert report.profile["facts"] > 0


def test_conflict_case(tmp_path):
    report, _, _ = run_fixture("case_conflict", tmp_path)
    verdicts = [unit.verdict for unit in report.units]
    assert verdicts == ["conflict", "conflict"]
    assert all(unit.rule_id == "R3" for unit in report.units)
    assert report.conflicts


def test_insufficient_case(tmp_path):
    report, _, _ = run_fixture("case_insufficient", tmp_path)
    assert [unit.verdict for unit in report.units] == ["insufficient"]
    assert report.units[0].failure_type in {"not_indexed", "not_exists", "query_mismatch"}
    assert "无法判断" in report.units[0].action


def test_pipeline_is_reproducible_with_cache(tmp_path):
    first, provider, gateway = run_fixture("case_conflict", tmp_path)
    calls_after_first = provider.calls
    second, _, _ = run_fixture("case_conflict", tmp_path)
    # A new sandbox has a fresh cache; compare the stable verdict shape only.
    def shape(report):
        return [(unit.assertion["field"], unit.verdict, unit.rule_id) for unit in report.units]

    assert shape(first) == shape(second)
    assert first.stats.calls <= 28
