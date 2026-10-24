import time
from pathlib import Path

from fastapi.testclient import TestClient

from claimlab.api import create_app
from claimlab.config import Settings
from claimlab.llm.client import FakeLLM
from claimlab.runtime import Sandbox
from claimlab.search.fake import FakeSearchProvider

PAGES = [
    {
        "_triggers": ["西安城墙"],
        "title": "西安城墙历史沿革",
        "url": "https://www.stats.gov.cn/a",
        "date": "2025-01-01",
        "passage": "西安城墙现存主体为明代修建。",
        "content": "西安城墙现存主体为明代修建。",
    }
]


def make_app(tmp_path: Path, *, allow_fake: bool = True):
    settings = Settings(
        search_provider="fake",
        search_api_key="",
        llm_api_key="",
        allow_fake_search=allow_fake,
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
    sandbox = Sandbox(settings, {"fake": FakeSearchProvider(PAGES)}, {}, FakeLLM())
    return create_app(settings, sandbox), sandbox


def test_api_has_no_examples_and_forbids_old_fields(tmp_path):
    app, _ = make_app(tmp_path)
    client = TestClient(app)
    assert client.get("/api/examples").status_code == 404
    assert client.get("/api/fixtures").status_code == 404
    response = client.post("/api/research", json={"text": "测试", "example_id": "q1"})
    assert response.status_code == 422
    assert client.post("/api/research", json={"text": "测试", "subject": "x"}).status_code == 422


def test_plan_id_reuses_exact_queries(tmp_path):
    app, _ = make_app(tmp_path)
    client = TestClient(app)
    question = "西安城墙现存主体是什么年代修建的？"
    plan = client.post("/api/plan", json={"text": question})
    assert plan.status_code == 200
    plan_data = plan.json()
    assert plan_data["plan_id"]
    response = client.post("/api/research", json={"text": question, "plan_id": plan_data["plan_id"]})
    assert response.status_code == 200
    data = response.json()
    assert data["plan_reused"] is True
    assert [q["query"] for q in data["queries"][: len(plan_data["queries"])]] == [q["query"] for q in plan_data["queries"]]
    assert data["answer"]["engine"] == "rule"


def test_research_rejects_safety_and_missing_key(tmp_path):
    app, _ = make_app(tmp_path)
    client = TestClient(app)
    assert client.post("/api/research", json={"text": "这次选举的结果如何"}).status_code == 400
    assert client.post("/api/research", json={"text": "长" * 4001}).status_code in {400, 422}

    app2, _ = make_app(tmp_path, allow_fake=False)
    client2 = TestClient(app2)
    assert client2.post("/api/research", json={"text": "测试"}).status_code == 503


def test_claim_run_streams_to_report(tmp_path):
    app, _ = make_app(tmp_path)
    client = TestClient(app)
    response = client.post("/api/runs", json={"text": "示例泡馍（回民街店）人均68元，周一闭店。"})
    assert response.status_code == 200
    run_id = response.json()["run_id"]
    for _ in range(40):
        snapshot = client.get("/api/runs/" + run_id).json()
        if snapshot["status"] in {"done", "error"}:
            break
        time.sleep(0.05)
    assert snapshot["status"] == "done"
    report = client.get("/api/report/" + run_id)
    assert report.status_code == 200


def test_question_is_rejected_with_guidance(tmp_path):
    app, _ = make_app(tmp_path)
    client = TestClient(app)
    response = client.post("/api/runs", json={"text": "西安城墙现存主体是什么年代修建的？"})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "question_not_claim"
    assert detail["message"]
