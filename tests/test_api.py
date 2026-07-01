import json
import time

import pytest
import yaml
from fastapi.testclient import TestClient


def _write_fake_completed_run(runs_dir, run_id="run_20260701_000000_aaaa"):
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    manifest = {
        "run_id": run_id,
        "user_request": "测试 RSI 因子在 AAPL 上的表现",
        "created_at": "2026-07-01T00:00:00+00:00",
        "summary": "Sharpe 1.1, preliminary result.",
        "metrics": {"sharpe": 1.1, "annual_return": 0.18},
        "warnings": ["DATA IS SYNTHETIC, NOT REAL MARKET DATA."],
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "config.yaml").write_text(yaml.safe_dump({"hypothesis": "test"}), encoding="utf-8")
    (run_dir / "equity_curve.png").write_bytes(b"\x89PNG\r\n\x1a\n fake png bytes")
    (run_dir / "research_note.md").write_text("# Research Note\n", encoding="utf-8")
    (run_dir / "backtest_result.json").write_text(json.dumps({"metrics": {"sharpe": 1.1}}), encoding="utf-8")
    return run_dir


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("quantbench.api.run_reader.RUNS_DIR", tmp_path)
    from quantbench.api.server import app

    return TestClient(app)


def test_list_runs_returns_summaries(tmp_path, client):
    _write_fake_completed_run(tmp_path)

    response = client.get("/api/runs")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["run_id"] == "run_20260701_000000_aaaa"
    assert body[0]["status"] == "completed"
    assert body[0]["sharpe"] == 1.1
    assert body[0]["warnings_count"] == 1


def test_get_run_detail_includes_artifacts_and_summary(tmp_path, client):
    _write_fake_completed_run(tmp_path)

    response = client.get("/api/runs/run_20260701_000000_aaaa")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == "Sharpe 1.1, preliminary result."
    assert body["metrics"]["sharpe"] == 1.1
    assert "DATA IS SYNTHETIC" in body["warnings"][0]
    filenames = {a["filename"] for a in body["artifacts"]}
    assert filenames == {"equity_curve.png", "research_note.md", "backtest_result.json"}
    kinds = {a["filename"]: a["kind"] for a in body["artifacts"]}
    assert kinds["equity_curve.png"] == "image"
    assert kinds["research_note.md"] == "markdown"
    assert kinds["backtest_result.json"] == "json"


def test_get_run_detail_backfills_summary_and_metrics_for_legacy_runs(tmp_path, client):
    """Runs recorded before `summary`/`metrics` were added to manifest.json must
    still render correctly, derived from `steps` and the conversation log."""
    run_id = "run_20260701_legacy_0001"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True)
    manifest = {
        "run_id": run_id,
        "user_request": "旧版 run，没有 summary/metrics 字段",
        "created_at": "2026-07-01T00:00:00+00:00",
        "warnings": [],
        "conversation_log": "conversation.json",
        "steps": [
            {"tool": "fetch_ohlcv", "args": {}, "result": {"rows": 100}},
            {
                "tool": "run_signal_backtest",
                "args": {},
                "result": {"sharpe": 1.42, "annual_return": 0.18, "warnings": []},
            },
        ],
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "conversation.json").write_text(
        json.dumps(
            [
                {"role": "user", "content": "..."},
                {"role": "assistant", "content": None, "tool_calls": [{"id": "c1"}]},
                {"role": "tool", "content": "..."},
                {"role": "assistant", "content": "Sharpe 1.42, preliminary."},
            ]
        ),
        encoding="utf-8",
    )

    response = client.get(f"/api/runs/{run_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == "Sharpe 1.42, preliminary."
    assert body["metrics"]["sharpe"] == 1.42


def test_get_run_detail_404_for_unknown_run(client):
    response = client.get("/api/runs/does_not_exist")
    assert response.status_code == 404


def test_get_artifact_serves_file_content(tmp_path, client):
    _write_fake_completed_run(tmp_path)

    response = client.get("/api/runs/run_20260701_000000_aaaa/artifacts/research_note.md")

    assert response.status_code == 200
    assert "# Research Note" in response.text


def test_get_artifact_rejects_path_traversal(tmp_path, client):
    _write_fake_completed_run(tmp_path)

    response = client.get("/api/runs/run_20260701_000000_aaaa/artifacts/..%2F..%2Fetc%2Fpasswd")

    assert response.status_code in (400, 404)


def test_list_runs_shows_request_and_today_for_in_progress_run(tmp_path, client):
    """A run still in progress has no manifest.json yet - user_request and
    created_at must still show up (from request.txt / the run_id itself)
    instead of going blank / sorting into an 'Unknown' date group."""
    from quantbench.artifact.store import ArtifactStore

    store = ArtifactStore(tmp_path)
    store.create_run("一个还在跑的请求")

    response = client.get("/api/runs")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["status"] == "running"
    assert body[0]["user_request"] == "一个还在跑的请求"
    assert body[0]["created_at"]  # non-empty, parseable date


def test_create_run_starts_in_background_and_completes(tmp_path, monkeypatch):
    from _fakes import FakeLLMClient

    monkeypatch.setattr("quantbench.api.run_reader.RUNS_DIR", tmp_path)
    monkeypatch.setattr("quantbench.data.cache.DATA_CACHE_DIR", tmp_path / "data_cache")
    monkeypatch.setattr(
        "quantbench.agent.coordinator.LLMClient",
        lambda model: FakeLLMClient(
            [
                ("tools", [("fetch_ohlcv", {"symbol": "BTC/USDT", "timeframe": "4h", "start": "2023-01-01", "end": "2023-02-01"})]),
                ("tools", [("run_signal_backtest", {"code": "def compute(df):\n    return df['close'].pct_change().fillna(0.0)\n", "cost_bps": 5})]),
                ("text", "done, preliminary"),
            ]
        ),
    )

    import quantbench.api.run_manager as run_manager_mod
    from quantbench.artifact.store import ArtifactStore

    monkeypatch.setattr(run_manager_mod, "RUNS_DIR", tmp_path)
    from quantbench.api.server import app

    # Rebuild the manager against the patched RUNS_DIR (module-level singleton
    # was already constructed against the real RUNS_DIR at import time).
    from quantbench.api import server as server_mod

    server_mod._manager = run_manager_mod.RunManager(run_store=ArtifactStore(tmp_path))

    client = TestClient(app)
    response = client.post("/api/runs", json={"request": "测试一个简单信号"})
    assert response.status_code == 200
    run_id = response.json()["run_id"]
    assert response.json()["status"] == "running"

    deadline = time.time() + 10
    status = "running"
    while time.time() < deadline:
        status = client.get(f"/api/runs/{run_id}/status").json()["status"]
        if status != "running":
            break
        time.sleep(0.1)

    assert status == "completed"
    detail = client.get(f"/api/runs/{run_id}").json()
    assert detail["metrics"]


def test_create_run_rejects_empty_request(client):
    response = client.post("/api/runs", json={"request": "   "})
    assert response.status_code == 400
