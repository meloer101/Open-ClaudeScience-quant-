import json
from pathlib import Path

import pandas as pd
import pytest
import yaml


def _cross_sectional_panel(symbols=("AAA", "BBB", "CCC", "DDD"), n=20):
    frames = []
    for i, symbol in enumerate(symbols):
        idx = pd.date_range("2024-01-01", periods=n, freq="1D", tz="UTC")
        base = 100 + i * 10
        trend = 1 + i * 0.01
        close = base + pd.Series(range(n), dtype="float64") * trend
        frames.append(
            pd.DataFrame(
                {
                    "timestamp": idx,
                    "symbol": symbol,
                    "open": close,
                    "high": close + 1,
                    "low": close - 1,
                    "close": close,
                    "volume": 1000.0,
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def test_cross_sectional_backtest_result_exposes_weights_matching_turnover_input():
    from quantbench.engine.cross_sectional_backtest import run_cross_sectional_backtest

    panel = _cross_sectional_panel()

    def compute(df):
        return df["close"].pct_change(1).fillna(0.0)

    result = run_cross_sectional_backtest(panel, compute, n_groups=2, cost_bps=0)

    assert not result.weights.empty
    # turnover is derived from the same weights matrix - recomputing it from
    # the exposed field must reproduce the engine's own turnover series.
    recomputed_turnover = (
        result.weights.diff().abs().sum(axis=1).div(2).fillna(result.weights.abs().sum(axis=1))
    )
    pd.testing.assert_series_equal(recomputed_turnover, result.turnover, check_names=False)


def _write_cross_sectional_run(runs_dir: Path, run_id: str, symbols=("AAA", "BBB", "CCC", "DDD")):
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    code = "def compute(df):\n    return df['close'].pct_change(1).fillna(0.0)\n"
    manifest = {
        "run_id": run_id,
        "user_request": "cross-sectional momentum",
        "created_at": "2024-01-20T00:00:00+00:00",
        "summary": "done",
        "metrics": {"sharpe": 1.0},
        "review": {"verdict": "STRONG", "verdict_reason": "reason", "findings": []},
        "warnings": [],
    }
    config = {"hypothesis": "cross-sectional momentum", "universe": {"symbols": list(symbols), "asset_class": "equity"}}
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "review_report.json").write_text(json.dumps(manifest["review"]), encoding="utf-8")
    (run_dir / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    (run_dir / "signal.py").write_text(code, encoding="utf-8")
    return run_dir


def _write_single_asset_run(runs_dir: Path, run_id: str):
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    code = "def compute(df):\n    return df['close'].pct_change(5).fillna(0.0)\n"
    manifest = {
        "run_id": run_id,
        "user_request": "single asset momentum",
        "created_at": "2024-01-20T00:00:00+00:00",
        "summary": "done",
        "metrics": {"sharpe": 1.0},
        "review": {"verdict": "STRONG", "verdict_reason": "reason", "findings": []},
        "warnings": [],
    }
    config = {
        "hypothesis": "single asset momentum",
        "data_path": "/tmp/does-not-matter.parquet",
        "universe": None,
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "review_report.json").write_text(json.dumps(manifest["review"]), encoding="utf-8")
    (run_dir / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    (run_dir / "signal.py").write_text(code, encoding="utf-8")
    return run_dir


@pytest.fixture
def patched_runs(tmp_path, monkeypatch):
    runs_dir = tmp_path / "runs"
    monkeypatch.setattr("quantbench.api.run_reader.RUNS_DIR", runs_dir)
    return runs_dir


def test_build_signal_export_produces_expected_schema(patched_runs, tmp_path, monkeypatch):
    from quantbench.factors import signal_export as se_mod
    from quantbench.factors.entry import build_entry_from_run

    _write_cross_sectional_run(patched_runs, "run_xs")
    entry = build_entry_from_run("run_xs", "cross_momentum")

    fake_weights = pd.Series({"AAA": 0.5, "BBB": -0.5, "CCC": 0.0, "DDD": 0.0}, name=pd.Timestamp("2024-01-20", tz="UTC"))
    monkeypatch.setattr(se_mod, "refresh_and_recompute_weights", lambda run_id, conn=None: fake_weights)

    payload = se_mod.build_signal_export(entry, conn=None)

    assert payload["factor_name"] == "cross_momentum"
    assert payload["factor_version_hash"].startswith("sha256:")
    assert payload["source_run_id"] == "run_xs"
    assert payload["source_verdict"] == "STRONG"
    assert payload["lifecycle_state"] == "paper_tracking"
    assert payload["target_weights"] == {"AAA": 0.5, "BBB": -0.5, "CCC": 0.0, "DDD": 0.0}
    assert payload["as_of"] == "2024-01-20 00:00:00+00:00"
    assert "known_limitations" in payload


def test_build_signal_export_returns_structured_error_for_single_asset_factor(patched_runs, tmp_path, monkeypatch):
    from quantbench.factors import signal_export as se_mod
    from quantbench.factors.entry import build_entry_from_run

    _write_single_asset_run(patched_runs, "run_single")
    entry = build_entry_from_run("run_single", "single_momentum")

    monkeypatch.setattr(se_mod, "refresh_and_recompute_weights", lambda run_id, conn=None: None)

    payload = se_mod.build_signal_export(entry, conn=None)

    assert "error" in payload
    assert "not supported" in payload["error"]


def test_factor_export_cli_json_and_human_output(patched_runs, tmp_path, monkeypatch):
    from quantbench.cli import main
    from quantbench.factors import signal_export as se_mod
    from click.testing import CliRunner

    monkeypatch.setattr("quantbench.cli.DEFAULT_FACTORS_DIR", tmp_path / "factors")
    _write_cross_sectional_run(patched_runs, "run_xs")

    runner = CliRunner()
    saved = runner.invoke(main, ["factor", "save", "run_xs", "--name", "cross_momentum"])
    assert saved.exit_code == 0, saved.output

    fake_weights = pd.Series({"AAA": 0.5, "BBB": -0.5}, name=pd.Timestamp("2024-01-20", tz="UTC"))
    monkeypatch.setattr(se_mod, "refresh_and_recompute_weights", lambda run_id, conn=None: fake_weights)

    json_result = runner.invoke(main, ["factor", "export", "cross_momentum", "--json-output"])
    assert json_result.exit_code == 0, json_result.output
    payload = json.loads(json_result.output)
    assert payload["target_weights"] == {"AAA": 0.5, "BBB": -0.5}

    human_result = runner.invoke(main, ["factor", "export", "cross_momentum"])
    assert human_result.exit_code == 0, human_result.output
    assert "AAA: 0.500000" in human_result.output
    assert "factor_version_hash:" in human_result.output
