import json

import numpy as np
import pandas as pd
import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient

COMPUTE_MOMENTUM = "def compute(df):\n    return df['close'].pct_change(5).fillna(0.0)\n"


@pytest.fixture(autouse=True)
def _patch_dirs(tmp_path, monkeypatch):
    # run_reader resolves run directories via its own module-level RUNS_DIR
    # constant (see tests/test_phase9_portfolio.py for the same pattern), and
    # the DuckDB warehouse defaults to a file under DATA_CACHE_DIR - both must
    # be redirected into tmp_path or tests would read/write the real project's
    # runs/ and data_cache/quantbench.duckdb.
    monkeypatch.setattr("quantbench.api.run_reader.RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr("quantbench.data.warehouse.DATA_CACHE_DIR", tmp_path / "data_cache")


def _idx(n: int, start: str = "2023-01-01", freq: str = "1D") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq=freq, tz="UTC")


def _ohlcv_df(n: int, start: str = "2023-01-01", freq: str = "1D", seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = _idx(n, start, freq)
    close = 100.0 * np.cumprod(1 + rng.normal(0.0005, 0.01, n))
    return pd.DataFrame(
        {
            "timestamp": idx,
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1000.0,
        }
    )


def _build_signal_run(tmp_path, verdict: str, symbol: str = "AAPL", n_hist: int = 120, seed: int = 0):
    """Builds a fixture single-symbol run directly on disk (bypassing the
    Coordinator/LLM loop) with everything quantbench.monitor.pipeline needs:
    signal.py, a cached source parquet, backtest_result.json, config.yaml
    with fetch_params/data_path, and a finalized manifest.json with the given
    verdict."""
    from quantbench.artifact.store import ArtifactStore
    from quantbench.engine.vectorized_backtest import run_vectorized_backtest
    from quantbench.skills.codeexec import run_signal_code

    store = ArtifactStore(tmp_path / "runs")
    run = store.create_run(f"monitor fixture {symbol}")
    run.save_code("signal.py", COMPUTE_MOMENTUM)

    old_df = _ohlcv_df(n_hist, start="2023-01-01", seed=seed)
    old_path = run.run_dir / "source_data.parquet"
    old_df.to_parquet(old_path, index=False)

    signal = run_signal_code(COMPUTE_MOMENTUM, old_df)
    backtest = run_vectorized_backtest(old_df, signal, cost_bps=5.0)
    run.save_json("backtest_result.json", backtest.to_json_dict())

    run.save_config(
        {
            "fetch_params": {"symbol": symbol, "timeframe": "1d", "start": "2023-01-01", "end": "2023-06-01"},
            "data_path": str(old_path),
        }
    )
    run.finalize(
        data_hash="sha256:test",
        code_hash="sha256:test",
        metrics=backtest.metrics,
        review={"verdict": verdict, "verdict_reason": "test fixture", "findings": []},
    )
    return run.run_id, backtest


def _fake_refresh_symbol(recent_df: pd.DataFrame):
    def _fake(symbol, timeframe, start=None, lookback_days=None, conn=None):
        return {
            "symbol": symbol,
            "start": str(recent_df["timestamp"].iloc[0]),
            "end": str(recent_df["timestamp"].iloc[-1]),
            "rows_upserted": len(recent_df),
            "source": "fake",
            "df": recent_df,
        }

    return _fake


# ---------------------------------------------------------------------------
# quantbench/monitor/decay.py - pure function
# ---------------------------------------------------------------------------


def test_compute_decay_report_ok_watch_alert():
    from quantbench.engine.metrics import annualized_sharpe, periods_per_year_from_timestamps
    from quantbench.monitor.decay import STATUS_ALERT, STATUS_OK, STATUS_WATCH, compute_decay_report

    recent = pd.Series(np.random.default_rng(7).normal(0.01, 0.01, 60), index=_idx(60))
    ppy = periods_per_year_from_timestamps(recent.index)
    recent_sharpe = annualized_sharpe(recent, ppy)
    assert recent_sharpe > 0

    ok = compute_decay_report(recent_sharpe, recent, recent.index[0])
    assert ok.status == STATUS_OK
    assert ok.sharpe_decay_ratio == pytest.approx(1.0, rel=1e-6)

    watch = compute_decay_report(recent_sharpe / 0.7, recent, recent.index[0])
    assert watch.status == STATUS_WATCH

    alert = compute_decay_report(recent_sharpe / 0.3, recent, recent.index[0])
    assert alert.status == STATUS_ALERT


def test_compute_decay_report_positive_to_negative_sharpe_is_alert_not_watch():
    """A STRONG/PROMISING run whose recent Sharpe has flipped negative is
    worse than a >50% decay - it must be alert, not merely watch, even
    though the ratio itself isn't a meaningful number to report."""
    from quantbench.monitor.decay import STATUS_ALERT, compute_decay_report

    recent = pd.Series(np.random.default_rng(3).normal(-0.01, 0.01, 30), index=_idx(30))
    report = compute_decay_report(1.2, recent, recent.index[0])

    assert report.recent_sharpe is not None and report.recent_sharpe < 0
    assert report.status == STATUS_ALERT
    assert report.sharpe_decay_ratio is None


def test_compute_decay_report_insufficient_observations():
    from quantbench.monitor.decay import STATUS_INSUFFICIENT_DATA, compute_decay_report

    tiny = pd.Series([0.01, -0.005, 0.02], index=_idx(3))
    report = compute_decay_report(1.0, tiny, tiny.index[0])
    assert report.status == STATUS_INSUFFICIENT_DATA
    assert report.sharpe_decay_ratio is None
    assert report.recent_sharpe is None


# ---------------------------------------------------------------------------
# quantbench/data/refresh.py - incremental upsert idempotency
# ---------------------------------------------------------------------------


def test_refresh_symbol_is_idempotent_on_overlap(tmp_path, monkeypatch):
    from quantbench.data import refresh as refresh_mod
    from quantbench.data.warehouse import get_connection, query_universe_ohlcv

    df = _ohlcv_df(5, start="2024-01-01")
    monkeypatch.setattr(refresh_mod, "fetch_ohlcv", lambda symbol, timeframe, start, end: (None, df, {}))

    conn = get_connection(tmp_path / "wh.duckdb")
    refresh_mod.refresh_symbol("FAKE", "1d", conn=conn)
    refresh_mod.refresh_symbol("FAKE", "1d", conn=conn)  # same overlapping window again

    result = query_universe_ohlcv(conn, ["FAKE"], "2020-01-01", "2030-01-01")
    assert len(result) == 5


# ---------------------------------------------------------------------------
# quantbench/monitor/pipeline.py - end to end
# ---------------------------------------------------------------------------


def test_check_run_decay_skips_non_alive_verdicts(tmp_path):
    from quantbench.monitor.pipeline import check_run_decay

    run_id, _ = _build_signal_run(tmp_path, verdict="WEAK")
    result = check_run_decay(run_id)

    assert result["skipped"]
    assert result["verdict"] == "WEAK"
    assert not (tmp_path / "runs" / run_id / "monitoring_report.json").exists()


def test_check_run_decay_single_symbol_writes_history_and_manifest(tmp_path, monkeypatch):
    from quantbench.data.warehouse import get_connection
    from quantbench.monitor import pipeline as pipeline_mod

    run_id, _ = _build_signal_run(tmp_path, verdict="STRONG")
    recent_df = _ohlcv_df(10, start="2023-06-02", seed=99)
    monkeypatch.setattr(pipeline_mod, "refresh_symbol", _fake_refresh_symbol(recent_df))

    conn = get_connection(tmp_path / "wh.duckdb")
    result = pipeline_mod.check_run_decay(run_id, conn=conn)

    assert result["status"] in {"ok", "watch", "alert", "insufficient_data"}
    assert result["recent_observations"] > 0

    run_dir = tmp_path / "runs" / run_id
    history = json.loads((run_dir / "monitoring_report.json").read_text(encoding="utf-8"))
    assert len(history) == 1
    assert history[0]["status"] == result["status"]

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["live_monitoring"]["status"] == result["status"]

    # A second check appends rather than overwriting the history.
    pipeline_mod.check_run_decay(run_id, conn=conn)
    history_after = json.loads((run_dir / "monitoring_report.json").read_text(encoding="utf-8"))
    assert len(history_after) == 2


def test_check_run_decay_refreshes_from_since_timestamp_not_fixed_lookback(tmp_path, monkeypatch):
    """Regression: refresh must cover from the run's own data cutoff (minus a
    small overlap buffer), not a fixed MONITOR_REFRESH_LOOKBACK_DAYS window -
    otherwise a run whose data is old would silently only get its last ~10
    days refreshed while still being reported as checked "since creation"."""
    from quantbench.data import refresh as refresh_mod
    from quantbench.data.warehouse import get_connection
    from quantbench.monitor import pipeline as pipeline_mod

    run_id, backtest = _build_signal_run(tmp_path, verdict="STRONG", n_hist=120, seed=17)
    since_timestamp = backtest.returns.index.max()

    captured_starts = []

    def fake_fetch_ohlcv(symbol, timeframe, start, end):
        captured_starts.append(start)
        recent_df = _ohlcv_df(30, start=start, seed=123)
        return None, recent_df, {"provider": "fake", "source": "fake"}

    monkeypatch.setattr(refresh_mod, "fetch_ohlcv", fake_fetch_ohlcv)

    conn = get_connection(tmp_path / "wh.duckdb")
    pipeline_mod.check_run_decay(run_id, conn=conn)

    assert len(captured_starts) == 1
    called_start = pd.Timestamp(captured_starts[0], tz="UTC")
    # since_timestamp is years in the past relative to this test's real
    # "today" - if refresh still used a fixed lookback window from today, the
    # captured start would be off by years instead of days.
    assert abs((called_start - since_timestamp).days) <= 15


def test_check_run_decay_portfolio_branch_combines_constituents(tmp_path, monkeypatch):
    from quantbench.artifact.store import ArtifactStore
    from quantbench.data.warehouse import get_connection
    from quantbench.monitor import pipeline as pipeline_mod
    from quantbench.portfolio.combine import combine

    run_id_a, backtest_a = _build_signal_run(tmp_path, verdict="STRONG", symbol="AAA", seed=1)
    run_id_b, backtest_b = _build_signal_run(tmp_path, verdict="STRONG", symbol="BBB", seed=2)

    store = ArtifactStore(tmp_path / "runs")
    port_run = store.create_run("portfolio fixture")
    weights = {run_id_a: 0.5, run_id_b: 0.5}
    port_run.save_json("portfolio_weights.json", weights)

    returns_df = pd.DataFrame({run_id_a: backtest_a.returns, run_id_b: backtest_b.returns})
    combined = combine(returns_df, weights, cost_bps=5.0)
    port_run.save_json("backtest_result.json", combined.to_json_dict())
    port_run.save_config(
        {"constituent_run_ids": [run_id_a, run_id_b], "portfolio_method": "risk_parity", "asset_class": "equity"}
    )
    port_run.finalize(
        data_hash="sha256:test",
        code_hash="sha256:test",
        metrics=combined.metrics,
        review={"verdict": "STRONG", "verdict_reason": "test fixture", "findings": []},
    )

    recent_df = _ohlcv_df(10, start="2023-06-02", seed=42)
    monkeypatch.setattr(pipeline_mod, "refresh_symbol", _fake_refresh_symbol(recent_df))

    conn = get_connection(tmp_path / "wh.duckdb")
    result = pipeline_mod.check_run_decay(port_run.run_id, conn=conn)

    assert result["status"] in {"ok", "watch", "alert", "insufficient_data"}
    history = json.loads((tmp_path / "runs" / port_run.run_id / "monitoring_report.json").read_text(encoding="utf-8"))
    assert len(history) == 1


def test_run_monitor_pass_only_checks_alive_runs(tmp_path, monkeypatch):
    from quantbench.monitor import pipeline as pipeline_mod

    strong_id, _ = _build_signal_run(tmp_path, verdict="STRONG", symbol="STR")
    weak_id, _ = _build_signal_run(tmp_path, verdict="WEAK", symbol="WK")

    recent_df = _ohlcv_df(10, start="2023-06-02", seed=5)
    monkeypatch.setattr(pipeline_mod, "refresh_symbol", _fake_refresh_symbol(recent_df))

    results = pipeline_mod.run_monitor_pass()
    checked_ids = {item["run_id"] for item in results}
    assert strong_id in checked_ids
    assert weak_id not in checked_ids


def _build_cross_sectional_run(tmp_path, code: str, symbols=tuple(f"S{i:02d}" for i in range(12))):
    """Minimal on-disk cross-sectional run (config.universe with symbols +
    signal.py) so the pipeline's cross-sectional branch of _refresh_and_backtest
    can be driven directly."""
    from quantbench.artifact.store import ArtifactStore

    store = ArtifactStore(tmp_path / "runs")
    run = store.create_run("cross-sectional monitor fixture")
    run.save_code("signal.py", code)
    run.save_config({"universe": {"symbols": list(symbols), "asset_class": "equity"}})
    run.finalize(
        data_hash="sha256:test",
        code_hash="sha256:test",
        metrics={},
        review={"verdict": "STRONG", "verdict_reason": "test fixture", "findings": []},
    )
    return run.run_id


def _cross_sectional_panel(symbols=tuple(f"S{i:02d}" for i in range(12)), n=40):
    frames = []
    for i, symbol in enumerate(symbols):
        df = _ohlcv_df(n, start="2023-01-01", seed=i)
        df["symbol"] = symbol
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def test_refresh_and_backtest_cross_sectional_goes_through_sandbox(tmp_path, monkeypatch):
    """The cross-sectional monitoring re-run must route model code through the
    sandbox (run_signal_code_panel), same as the coordinator and screen paths -
    otherwise a runaway factor would stall the background monitor process."""
    from quantbench.monitor import pipeline as pipeline_mod

    panel = _cross_sectional_panel()
    monkeypatch.setattr(pipeline_mod, "refresh_universe", lambda *a, **k: None)
    monkeypatch.setattr(pipeline_mod, "query_universe_ohlcv", lambda *a, **k: panel)

    good_id = _build_cross_sectional_run(tmp_path, "def compute(df):\n    return df['close'].pct_change(5).fillna(0.0)\n")
    returns = pipeline_mod.refresh_and_backtest(good_id, conn=None, refresh_start="2023-01-01")
    assert isinstance(returns, pd.Series)
    assert len(returns) > 0


def test_refresh_and_backtest_cross_sectional_isolates_infinite_loop(tmp_path, monkeypatch):
    from quantbench.monitor import pipeline as pipeline_mod
    from quantbench.skills.codeexec import run_signal_code_panel
    from quantbench.skills.sandbox import SandboxConfig, SandboxError

    panel = _cross_sectional_panel()
    monkeypatch.setattr(pipeline_mod, "refresh_universe", lambda *a, **k: None)
    monkeypatch.setattr(pipeline_mod, "query_universe_ohlcv", lambda *a, **k: panel)

    def _tight_panel_sandbox(code, panel, *, sandbox=None, usage_sink=None):
        return run_signal_code_panel(
            code, panel, sandbox=SandboxConfig(cpu_seconds=1, mem_mb=512, wall_timeout_s=2.0), usage_sink=usage_sink
        )

    monkeypatch.setattr(pipeline_mod, "run_signal_code_panel", _tight_panel_sandbox)

    loop_id = _build_cross_sectional_run(tmp_path, "def compute(df):\n    while True:\n        pass\n")
    with pytest.raises(SandboxError):
        pipeline_mod.refresh_and_backtest(loop_id, conn=None, refresh_start="2023-01-01")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_monitor_check_reports_skip_for_weak_run(tmp_path):
    from quantbench.cli import main

    run_id, _ = _build_signal_run(tmp_path, verdict="WEAK")
    result = CliRunner().invoke(main, ["monitor", "check", run_id])

    assert result.exit_code == 0, result.output
    assert "skipped" in result.output


def test_cli_monitor_check_all_alive(tmp_path, monkeypatch):
    import quantbench.monitor.pipeline as pipeline_mod
    from quantbench.cli import main

    strong_id, _ = _build_signal_run(tmp_path, verdict="STRONG")
    recent_df = _ohlcv_df(10, start="2023-06-02", seed=11)
    monkeypatch.setattr(pipeline_mod, "refresh_symbol", _fake_refresh_symbol(recent_df))

    result = CliRunner().invoke(main, ["monitor", "check", "--all-alive"])

    assert result.exit_code == 0, result.output
    assert strong_id in result.output


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_get_monitoring_report_endpoint(tmp_path):
    run_dir = tmp_path / "runs" / "run_x"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(json.dumps({"run_id": "run_x"}), encoding="utf-8")
    history = [
        {
            "status": "ok",
            "checked_at": "t",
            "since_timestamp": "t",
            "original_sharpe": 1.0,
            "recent_sharpe": 1.0,
            "sharpe_decay_ratio": 1.0,
            "recent_observations": 10,
            "recent_max_drawdown": -0.1,
            "detail": "x",
        }
    ]
    (run_dir / "monitoring_report.json").write_text(json.dumps(history), encoding="utf-8")

    from quantbench.api.server import app

    client = TestClient(app)
    response = client.get("/api/runs/run_x/monitoring")
    assert response.status_code == 200
    assert response.json()["history"] == history

    missing = client.get("/api/runs/run_y/monitoring")
    assert missing.status_code == 404


def test_trigger_monitoring_check_endpoint(tmp_path, monkeypatch):
    import quantbench.monitor.pipeline as pipeline_mod

    run_dir = tmp_path / "runs" / "run_y"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text(json.dumps({"run_id": "run_y"}), encoding="utf-8")

    monkeypatch.setattr(pipeline_mod, "check_run_decay", lambda run_id, conn=None: {"status": "ok"})

    from quantbench.api.server import app

    client = TestClient(app)
    response = client.post("/api/runs/run_y/monitoring/check")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    missing = client.post("/api/runs/does-not-exist/monitoring/check")
    assert missing.status_code == 404


def test_list_runs_includes_monitoring_status(tmp_path):
    run_dir = tmp_path / "runs" / "run_z"
    run_dir.mkdir(parents=True)
    manifest = {
        "run_id": "run_z",
        "user_request": "x",
        "created_at": "2026-01-01T00:00:00+00:00",
        "live_monitoring": {"status": "alert"},
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    from quantbench.api.server import app

    client = TestClient(app)
    response = client.get("/api/runs")
    assert response.status_code == 200
    body = response.json()
    assert body[0]["monitoring_status"] == "alert"
