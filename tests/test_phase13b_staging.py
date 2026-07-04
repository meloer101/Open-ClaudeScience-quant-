import json
import time

import pandas as pd
from fastapi.testclient import TestClient


def _factor_panel():
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-01", "2024-01-02"], utc=True),
            "symbol": ["AAA", "AAA", "BBB", "BBB"],
            "factor": [None, 0.2, 0.1, 0.3],
        }
    )


def test_validation_report_is_built_from_code_and_factor_panel_without_backtest(monkeypatch):
    from quantbench.agent.staging import build_validation_report

    def explode(*args, **kwargs):
        raise AssertionError("validation_report must not trigger the expensive backtest path")

    monkeypatch.setattr("quantbench.agent.coordinator.run_cross_sectional_backtest", explode)

    report = build_validation_report(
        "def compute(df):\n    return df['close'] / df['close'].shift(20) - 1\n",
        _factor_panel(),
        available_columns=["timestamp", "symbol", "open", "close", "volume"],
    )

    assert report.has_shift is True
    assert report.input_columns == ["close"]
    assert report.nan_ratio == 0.25
    assert report.coverage_ratio == 0.75
    assert report.output_aligned is True
    assert report.sample_head[0]["symbol"] == "AAA"
    assert report.sample_tail[-1]["factor"] == 0.3


def test_gate_policy_auto_passes_clean_small_factor_and_stops_lookahead_or_large_screen():
    from quantbench.agent.staging import CostEstimate, StagingPolicy, ValidationReport, should_stage

    clean = ValidationReport(
        lookahead_issues=[],
        has_shift=True,
        input_columns=["close"],
        nan_ratio=0.01,
        coverage_ratio=0.99,
        output_aligned=True,
        sample_head=[],
        sample_tail=[],
        data_quality={},
    )
    risky = ValidationReport(
        lookahead_issues=[{"pattern": "negative_period", "detail": ".shift(-1)", "line": 2}],
        has_shift=True,
        input_columns=["close"],
        nan_ratio=0.01,
        coverage_ratio=0.99,
        output_aligned=True,
        sample_head=[],
        sample_tail=[],
        data_quality={},
    )

    policy = StagingPolicy()
    assert should_stage(clean, CostEstimate(kind="single", observations=120), policy).should_stage is False
    assert should_stage(risky, CostEstimate(kind="single", observations=120), policy).should_stage is True
    large = should_stage(clean, CostEstimate(kind="screen", observations=10_000, candidates=8), policy)
    assert large.should_stage is True
    assert "high_cost" in large.reasons


def test_staged_diff_records_code_and_config_overrides():
    from quantbench.agent.staging import build_staged_diff

    diff = build_staged_diff(
        original_code="def compute(df):\n    return df.close\n",
        final_code="def compute(df):\n    return df.close.pct_change().fillna(0)\n",
        original_config={"cost_bps": 5, "execution": {"timing": "close"}},
        final_config={"cost_bps": 10, "execution": {"timing": "next_open"}},
    )

    assert diff["code_changed"] is True
    assert "-    return df.close" in diff["code_diff"]
    assert diff["config_changes"] == {
        "cost_bps": {"before": 5, "after": 10},
        "execution": {"before": {"timing": "close"}, "after": {"timing": "next_open"}},
    }


def test_api_staging_confirm_advances_waiting_run(tmp_path, monkeypatch):
    from _fakes import FakeLLMClient

    lookahead_code = "def compute(df):\n    return df['close'].shift(-1).fillna(0.0)\n"
    fixed_code = "def compute(df):\n    return df['close'].pct_change().fillna(0.0)\n"

    monkeypatch.setattr("quantbench.api.run_reader.RUNS_DIR", tmp_path)
    monkeypatch.setattr("quantbench.data.cache.DATA_CACHE_DIR", tmp_path / "data_cache")
    monkeypatch.setattr(
        "quantbench.agent.coordinator.LLMClient",
        lambda model: FakeLLMClient(
            [
                ("tools", [("fetch_ohlcv", {"symbol": "BTC/USDT", "timeframe": "4h", "start": "2023-01-01", "end": "2023-02-01"})]),
                ("tools", [("run_signal_backtest", {"code": lookahead_code, "cost_bps": 5})]),
                ("text", "done"),
            ]
        ),
    )

    import quantbench.api.run_manager as run_manager_mod
    from quantbench.artifact.store import ArtifactStore
    from quantbench.api import server as server_mod

    monkeypatch.setattr(run_manager_mod, "RUNS_DIR", tmp_path)
    server_mod._manager = run_manager_mod.RunManager(run_store=ArtifactStore(tmp_path))
    client = TestClient(server_mod.app)

    run_id = client.post("/api/runs", json={"request": "测试一个有未来函数嫌疑的信号"}).json()["run_id"]

    deadline = time.time() + 10
    status = "running"
    while time.time() < deadline:
        status = client.get(f"/api/runs/{run_id}/status").json()["status"]
        if status == "awaiting_confirmation":
            break
        time.sleep(0.05)

    assert status == "awaiting_confirmation"
    pending = json.loads((tmp_path / run_id / "staging_pending.json").read_text(encoding="utf-8"))
    assert pending["validation_report"]["lookahead_issues"]

    response = client.post(
        f"/api/runs/{run_id}/staging/confirm",
        json={"overrides": {"code": fixed_code, "config": {"cost_bps": 10}}},
    )
    assert response.status_code == 200

    deadline = time.time() + 10
    status = "running"
    while time.time() < deadline:
        status = client.get(f"/api/runs/{run_id}/status").json()["status"]
        if status != "running":
            break
        time.sleep(0.05)

    assert status == "completed"
    manifest = json.loads((tmp_path / run_id / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["staging"]["gate_decision"]["decision"] == "stopped"
    assert manifest["staging"]["overrides"]["config"]["cost_bps"] == 10
    assert manifest["staging"]["staged_diff"]["code_changed"] is True
    signal = (tmp_path / run_id / "signal.py").read_text(encoding="utf-8")
    assert fixed_code in signal
