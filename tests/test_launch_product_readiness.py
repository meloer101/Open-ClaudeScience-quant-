import json

from fastapi.testclient import TestClient


def test_devserver_plan_binds_localhost_and_sets_tokens():
    from quantbench.devserver import build_devserver_plan

    plan = build_devserver_plan(api_port=8765, web_port=8766, token="token")

    assert "--host" in plan.api_cmd
    assert "127.0.0.1" in plan.api_cmd
    assert plan.web_url == "http://127.0.0.1:8766"
    assert plan.env["QUANTBENCH_API_TOKEN"] == "token"
    assert plan.env["VITE_QUANTBENCH_API_TOKEN"] == "token"


def test_seed_example_runs_writes_browsable_artifacts(tmp_path):
    from quantbench.examples import EXAMPLE_RUN_ID, seed_example_runs

    result = seed_example_runs(tmp_path)
    run_dir = tmp_path / EXAMPLE_RUN_ID

    assert result["created"] == 1
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "review_report.json").exists()
    assert "not investment advice" in (run_dir / "research_note.md").read_text(encoding="utf-8").lower()


def test_cost_estimate_is_deterministic_and_positive():
    from quantbench.costing import estimate_request_cost

    estimate = estimate_request_cost("在标普500里测试20日动量截面因子")

    assert estimate["estimated_tokens"] >= 1200
    assert estimate["estimated_usd"] > 0
    assert estimate["coordinator_calls"] >= 1


def test_cost_estimate_api(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANTBENCH_API_TOKEN", "test-token")
    monkeypatch.setattr("quantbench.api.run_reader.RUNS_DIR", tmp_path)
    from quantbench.api.server import app

    client = TestClient(app, headers={"X-QuantBench-Token": "test-token"})
    response = client.post("/api/runs/estimate-cost", json={"request": "test a crypto momentum strategy"})

    assert response.status_code == 200
    assert response.json()["estimated_tokens"] >= 1200


def test_release_docs_exist_and_contain_required_checks():
    release = __import__("pathlib").Path("docs/RELEASE.md").read_text(encoding="utf-8")
    changelog = __import__("pathlib").Path("CHANGELOG.md").read_text(encoding="utf-8")

    assert "Run backend tests" in release
    assert "Run frontend lint/unit/build" in release
    assert "0.1.0-alpha" in changelog


def test_root_internal_docs_moved_to_docs_dev():
    from pathlib import Path

    root_docs = [path.name for path in Path(".").glob("PHASE*.md")]

    assert root_docs == []
    assert Path("docs/dev/PHASE13.md").exists()
