import json
import os
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
    monkeypatch.setenv("QUANTBENCH_API_TOKEN", "test-token")
    monkeypatch.setattr("quantbench.api.run_reader.RUNS_DIR", tmp_path)
    from quantbench.api.server import app

    return TestClient(app, headers={"X-QuantBench-Token": "test-token"})


def test_config_status_reflects_active_model_and_its_provider_key(client, monkeypatch):
    monkeypatch.delenv("QUANTBENCH_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert client.get("/api/config/status").json() == {
        "llm_key_configured": False,
        "model": "deepseek/deepseek-chat",
        "key_env": "DEEPSEEK_API_KEY",
    }

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    assert client.get("/api/config/status").json()["llm_key_configured"] is True

    monkeypatch.setenv("QUANTBENCH_MODEL", "openai/gpt-4o")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    body = client.get("/api/config/status").json()
    assert body == {"llm_key_configured": False, "model": "openai/gpt-4o", "key_env": "OPENAI_API_KEY"}


def test_post_llm_key_persists_model_and_key_to_env_file_and_current_process(client, tmp_path, monkeypatch):
    monkeypatch.delenv("QUANTBENCH_MODEL", raising=False)
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    monkeypatch.setattr("quantbench.api.llm_key.ENV_FILE", tmp_path / ".env")

    response = client.post("/api/config/llm-key", json={"model": "moonshot/kimi-k2", "api_key": "sk-live-123"})

    assert response.status_code == 200
    assert os.environ["QUANTBENCH_MODEL"] == "moonshot/kimi-k2"
    assert os.environ["MOONSHOT_API_KEY"] == "sk-live-123"
    env_contents = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "QUANTBENCH_MODEL=moonshot/kimi-k2" in env_contents
    assert "MOONSHOT_API_KEY=sk-live-123" in env_contents
    assert client.get("/api/config/status").json() == {
        "llm_key_configured": True,
        "model": "moonshot/kimi-k2",
        "key_env": "MOONSHOT_API_KEY",
    }


def test_post_llm_key_rejects_blank_key(client):
    response = client.post("/api/config/llm-key", json={"model": "deepseek/deepseek-chat", "api_key": "   "})

    assert response.status_code == 400


def test_post_llm_key_rejects_blank_model(client):
    response = client.post("/api/config/llm-key", json={"model": "   ", "api_key": "sk-test"})

    assert response.status_code == 400


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


def test_get_backtest_result_endpoint_returns_json(tmp_path, client):
    _write_fake_completed_run(tmp_path)

    response = client.get("/api/runs/run_20260701_000000_aaaa/backtest-result")

    assert response.status_code == 200
    assert response.json() == {"metrics": {"sharpe": 1.1}}


def test_get_backtest_result_falls_back_to_legacy_cross_sectional_filename(tmp_path, client):
    """Regression: cross-sectional runs used to save their result as
    "cross_sectional_backtest_result.json" before that was unified with the
    single-symbol path's "backtest_result.json". Historical run directories
    on disk still use the old name, and the ChartsPanel/Compare correlation
    must still be able to read them - not just runs created after the fix."""
    run_id = "run_20260630_000000_legacy"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    (run_dir / "manifest.json").write_text(json.dumps({"run_id": run_id}), encoding="utf-8")
    (run_dir / "cross_sectional_backtest_result.json").write_text(
        json.dumps({"metrics": {"sharpe": 0.8}, "series": {"timestamp": [], "long_short_returns": []}}),
        encoding="utf-8",
    )

    response = client.get(f"/api/runs/{run_id}/backtest-result")

    assert response.status_code == 200
    assert response.json()["metrics"] == {"sharpe": 0.8}


def test_get_backtest_result_404_when_missing(tmp_path, client):
    tmp_path.joinpath("run_20260701_000000_empty").mkdir()

    response = client.get("/api/runs/run_20260701_000000_empty/backtest-result")

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


def test_get_artifact_preview_returns_first_rows_of_parquet(tmp_path, client):
    import pandas as pd

    run_dir = _write_fake_completed_run(tmp_path)
    frame = pd.DataFrame({"symbol": [f"SYM{i}" for i in range(250)], "value": range(250)})
    frame.to_parquet(run_dir / "panel.parquet")

    response = client.get("/api/runs/run_20260701_000000_aaaa/artifacts/panel.parquet/preview")

    assert response.status_code == 200
    body = response.json()
    assert body["columns"] == ["symbol", "value"]
    assert len(body["rows"]) == 200
    assert body["rows"][0] == {"symbol": "SYM0", "value": 0}
    assert body["total_rows"] == 250
    assert body["truncated"] is True


def test_parquet_preview_does_not_materialize_full_file_into_pandas(tmp_path, monkeypatch):
    """Regression: preview_parquet() used to call pd.read_parquet(path) (the
    whole file) before slicing to 200 rows, so a large multi-symbol
    panel.parquet would be fully loaded into memory just to preview a
    handful of rows. It must now get total_rows from Parquet metadata and
    only decode the row groups it needs - i.e. never call pd.read_parquet
    on the full path at all."""
    import pandas as pd

    from quantbench.api import run_reader

    monkeypatch.setattr(run_reader, "RUNS_DIR", tmp_path)
    run_dir = tmp_path / "run_preview_test"
    run_dir.mkdir()
    frame = pd.DataFrame({"symbol": [f"SYM{i}" for i in range(600)], "value": range(600)})
    # Small row groups so a 200-row preview must span multiple groups without
    # forcing every group to be read - exercises the early-stop logic, not
    # just the case where one row group already covers the whole file.
    frame.to_parquet(run_dir / "panel.parquet", row_group_size=50)

    original_read_parquet = pd.read_parquet
    monkeypatch.setattr(
        pd,
        "read_parquet",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("preview_parquet must not call pd.read_parquet on the full file")),
    )
    try:
        preview = run_reader.preview_parquet("run_preview_test", "panel.parquet")
    finally:
        monkeypatch.setattr(pd, "read_parquet", original_read_parquet)

    assert preview["total_rows"] == 600
    assert preview["truncated"] is True
    assert len(preview["rows"]) == 200
    assert preview["rows"][0] == {"symbol": "SYM0", "value": 0}
    assert preview["rows"][-1] == {"symbol": "SYM199", "value": 199}


def test_get_artifact_preview_404_for_missing_file(tmp_path, client):
    _write_fake_completed_run(tmp_path)

    response = client.get("/api/runs/run_20260701_000000_aaaa/artifacts/does_not_exist.parquet/preview")

    assert response.status_code == 404


def test_get_artifact_preview_rejects_non_parquet(tmp_path, client):
    _write_fake_completed_run(tmp_path)

    response = client.get("/api/runs/run_20260701_000000_aaaa/artifacts/research_note.md/preview")

    assert response.status_code == 400


def test_get_artifact_preview_rejects_path_traversal(tmp_path, client):
    _write_fake_completed_run(tmp_path)

    response = client.get("/api/runs/run_20260701_000000_aaaa/artifacts/..%2F..%2Fetc%2Fpasswd/preview")

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

    monkeypatch.setenv("QUANTBENCH_API_TOKEN", "test-token")
    monkeypatch.setattr("quantbench.api.run_reader.RUNS_DIR", tmp_path)
    monkeypatch.setenv("QUANTBENCH_API_TOKEN", "test-token")
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

    client = TestClient(app, headers={"X-QuantBench-Token": "test-token"})
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


def test_stream_run_events_emits_tool_lifecycle_events(tmp_path, monkeypatch):
    from _fakes import FakeLLMClient

    monkeypatch.setattr("quantbench.api.run_reader.RUNS_DIR", tmp_path)
    monkeypatch.setenv("QUANTBENCH_API_TOKEN", "test-token")
    monkeypatch.setattr("quantbench.data.cache.DATA_CACHE_DIR", tmp_path / "data_cache")
    monkeypatch.setattr(
        "quantbench.agent.coordinator.LLMClient",
        lambda model: FakeLLMClient(
            [
                ("tools", [("fetch_ohlcv", {"symbol": "BTC/USDT", "timeframe": "4h", "start": "2023-01-01", "end": "2023-02-01"})]),
                ("tools", [("run_signal_backtest", {"code": "def compute(df):\n    return df['close'].pct_change().fillna(0.0)\n", "cost_bps": 5})]),
                ("text", "done"),
            ]
        ),
    )

    import quantbench.api.run_manager as run_manager_mod
    from quantbench.artifact.store import ArtifactStore

    monkeypatch.setattr(run_manager_mod, "RUNS_DIR", tmp_path)
    from quantbench.api import server as server_mod

    server_mod._manager = run_manager_mod.RunManager(run_store=ArtifactStore(tmp_path))
    test_client = TestClient(server_mod.app, headers={"X-QuantBench-Token": "test-token"})

    response = test_client.post("/api/runs", json={"request": "测试一个简单信号"})
    run_id = response.json()["run_id"]

    events = []
    with test_client.stream("GET", f"/api/runs/{run_id}/events") as stream:
        for line in stream.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: ") :]))
            if events and events[-1].get("type") == "final":
                break

    types = [e["type"] for e in events]
    assert types == ["start", "tool_start", "tool_end", "tool_start", "tool_end", "final"]
    assert events[1]["tool"] == "fetch_ohlcv"
    assert events[3]["tool"] == "run_signal_backtest"
    assert "sharpe" in events[4]["result"]
    assert events[-1]["summary"] == "done"


def test_stream_run_events_ends_immediately_for_untracked_run(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANTBENCH_API_TOKEN", "test-token")
    monkeypatch.setattr("quantbench.api.run_reader.RUNS_DIR", tmp_path)
    from quantbench.api.server import app

    test_client = TestClient(app, headers={"X-QuantBench-Token": "test-token"})
    with test_client.stream("GET", "/api/runs/some_unknown_run/events") as stream:
        lines = list(stream.iter_lines())
    assert lines == []


def test_create_run_rejects_empty_request(client):
    response = client.post("/api/runs", json={"request": "   "})
    assert response.status_code == 400


def _write_phase3_run(runs_dir, run_id, *, hypothesis="momentum AAPL", sharpe=1.0, verdict="PROMISING", parent=None):
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    findings = [
        {
            "check": "out_of_sample",
            "severity": "warning",
            "message": "decay",
            "detail": {"test_metrics": {"sharpe": sharpe - 0.2}},
        }
    ]
    manifest = {
        "run_id": run_id,
        "user_request": hypothesis,
        "created_at": "2026-07-01T00:00:00+00:00",
        "summary": "done",
        "metrics": {"sharpe": sharpe, "annual_return": 0.1},
        "warnings": [],
        "review": {"verdict": verdict, "verdict_reason": "reason", "findings": findings},
        "parent_run_id": parent,
    }
    config = {
        "hypothesis": hypothesis,
        "data_path": "/tmp/data_cache/yfinance_equity_AAPL_1d.parquet",
        "parent_run_id": parent,
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    (run_dir / "signal.py").write_text(f"def compute(df):\n    return df.close * {sharpe}\n", encoding="utf-8")


def test_library_api_summary_compare_and_lineage(tmp_path, client):
    _write_phase3_run(tmp_path, "run_20260701_000000_a", hypothesis="momentum AAPL", sharpe=1.0)
    _write_phase3_run(
        tmp_path,
        "run_20260701_000001_b",
        hypothesis="momentum AAPL 60d",
        sharpe=1.4,
        verdict="STRONG",
        parent="run_20260701_000000_a",
    )

    library_response = client.get("/api/library?verdict=PROMISING,STRONG&asset=equity&sort=sharpe")
    assert library_response.status_code == 200
    assert [row["run_id"] for row in library_response.json()] == ["run_20260701_000001_b", "run_20260701_000000_a"]

    summary_response = client.get("/api/library/summary")
    assert summary_response.status_code == 200
    assert summary_response.json()[0]["count"] == 2
    assert summary_response.json()[0]["sharpe_mean"] == pytest.approx(1.2)

    compare_response = client.get("/api/compare?run_ids=run_20260701_000000_a,run_20260701_000001_b")
    assert compare_response.status_code == 200
    assert compare_response.json()["metrics"]["sharpe"]["run_20260701_000001_b"] == 1.4
    # Phase 4: /api/compare also carries a returns_correlation matrix. Neither
    # fixture run has a backtest_result.json, so every cell must be null
    # (missing data), not a fabricated number - and the key must still exist
    # so the frontend doesn't have to special-case its absence.
    correlation = compare_response.json()["returns_correlation"]
    assert correlation["run_20260701_000000_a"]["run_20260701_000001_b"] is None

    single_run_compare = client.get("/api/compare?run_ids=run_20260701_000000_a")
    assert single_run_compare.json()["returns_correlation"] == {}

    lineage_response = client.get("/api/runs/run_20260701_000001_b/lineage")
    assert lineage_response.status_code == 200
    assert [node["run_id"] for node in lineage_response.json()["chain"]] == [
        "run_20260701_000000_a",
        "run_20260701_000001_b",
    ]


def test_fork_endpoint_delegates_to_run_manager(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANTBENCH_API_TOKEN", "test-token")
    monkeypatch.setattr("quantbench.api.run_reader.RUNS_DIR", tmp_path)
    from quantbench.api import server as server_mod

    class FakeManager:
        def fork(self, run_id, modification):
            assert run_id == "run_20260701_000000_a"
            assert modification == "把窗口改成60日"
            return "run_20260701_000002_fork"

    monkeypatch.setattr(server_mod, "_manager", FakeManager())
    test_client = TestClient(server_mod.app, headers={"X-QuantBench-Token": "test-token"})

    response = test_client.post("/api/runs/run_20260701_000000_a/fork", json={"modification": "把窗口改成60日"})

    assert response.status_code == 200
    assert response.json() == {"run_id": "run_20260701_000002_fork", "status": "running"}


def test_cancel_endpoint_404_for_unknown_run(tmp_path, client):
    response = client.post("/api/runs/some_unknown_run/cancel")
    assert response.status_code == 404


def test_cancel_endpoint_is_a_noop_for_a_completed_run(tmp_path, client):
    _write_fake_completed_run(tmp_path)

    response = client.post("/api/runs/run_20260701_000000_aaaa/cancel")

    assert response.status_code == 200
    assert response.json() == {"status": "completed"}


def test_cancel_endpoint_marks_orphaned_running_run_cancelled_after_restart(tmp_path, monkeypatch):
    """A run directory with no terminal marker is only "running" by filesystem
    inference. After an API restart there is no in-memory task to signal, so
    the cancel endpoint must write a terminal marker itself."""

    run_id = "run_20260701_000000_orphan"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    (run_dir / "request.txt").write_text("之前没跑完的任务", encoding="utf-8")
    monkeypatch.setenv("QUANTBENCH_API_TOKEN", "test-token")
    monkeypatch.setattr("quantbench.api.run_reader.RUNS_DIR", tmp_path)

    from quantbench.api import server as server_mod

    class FakeManager:
        def cancel(self, requested_run_id):
            assert requested_run_id == run_id
            return False

    monkeypatch.setattr(server_mod, "_manager", FakeManager())
    test_client = TestClient(server_mod.app, headers={"X-QuantBench-Token": "test-token"})

    response = test_client.post(f"/api/runs/{run_id}/cancel")

    assert response.status_code == 200
    assert response.json() == {"status": "cancelled"}
    assert test_client.get(f"/api/runs/{run_id}/status").json() == {"status": "cancelled"}


def test_cancel_endpoint_stops_a_run_before_it_reaches_the_step_limit(tmp_path, monkeypatch):
    from _fakes import FakeLLMClient

    class SlowFakeLLMClient(FakeLLMClient):
        """Adds a small delay per call so the test has a window to cancel
        mid-run instead of racing a run that would otherwise finish (or hit
        MAX_STEPS) before the cancel request lands."""

        def chat(self, messages, tools=None):
            time.sleep(0.05)
            return super().chat(messages, tools)

    fetch_args = {"symbol": "BTC/USDT", "timeframe": "4h", "start": "2023-01-01", "end": "2023-02-01"}
    fake = SlowFakeLLMClient([("tools", [("fetch_ohlcv", fetch_args)])] * 20)

    monkeypatch.setenv("QUANTBENCH_API_TOKEN", "test-token")
    monkeypatch.setattr("quantbench.api.run_reader.RUNS_DIR", tmp_path)
    monkeypatch.setattr("quantbench.data.cache.DATA_CACHE_DIR", tmp_path / "data_cache")
    monkeypatch.setattr("quantbench.agent.coordinator.LLMClient", lambda model: fake)

    import quantbench.api.run_manager as run_manager_mod
    from quantbench.artifact.store import ArtifactStore

    monkeypatch.setattr(run_manager_mod, "RUNS_DIR", tmp_path)
    from quantbench.api import server as server_mod

    server_mod._manager = run_manager_mod.RunManager(run_store=ArtifactStore(tmp_path))
    test_client = TestClient(server_mod.app, headers={"X-QuantBench-Token": "test-token"})

    run_id = test_client.post("/api/runs", json={"request": "测试一个简单信号"}).json()["run_id"]

    # Let one or two steps run, then stop it - this is the "stop" button's
    # request, and the whole point is that it must not require waiting for
    # all 20 scripted steps (or MAX_STEPS) to play out.
    time.sleep(0.12)
    cancel_response = test_client.post(f"/api/runs/{run_id}/cancel")
    assert cancel_response.status_code == 200

    deadline = time.time() + 10
    status = "running"
    while time.time() < deadline:
        status = test_client.get(f"/api/runs/{run_id}/status").json()["status"]
        if status != "running":
            break
        time.sleep(0.05)

    assert status == "cancelled"
    # The whole point of cancelling is to not burn through the rest of the
    # scripted (or MAX_STEPS) turns once the signal is set.
    assert len(fake.calls) < 20
