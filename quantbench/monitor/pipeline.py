from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from quantbench.api import run_reader
from quantbench.config import ALIVE_VERDICTS, DEFAULT_COST_BPS, MONITOR_REFRESH_LOOKBACK_DAYS
from quantbench.data.refresh import refresh_symbol, refresh_universe
from quantbench.data.warehouse import get_connection, query_universe_ohlcv
from quantbench.engine.cross_sectional_backtest import run_cross_sectional_backtest
from quantbench.engine.vectorized_backtest import run_vectorized_backtest
from quantbench.factors.compute_extract import extract_compute_source
from quantbench.monitor.decay import DecayReport, compute_decay_report
from quantbench.portfolio.combine import combine
from quantbench.skills.codeexec import run_signal_code, run_signal_code_panel

# config.yaml does not persist the exact timeframe/n_groups/cost_bps a
# cross-sectional or portfolio run used.
# Re-running for a decay check therefore approximates them from the run's
# recorded asset_class and the same coordinator.py tool defaults every new
# run already uses, rather than the run's own original values. This is a
# documented v1 limitation, not a silent guess: monitoring_report.json
# records which defaults were used.
_DEFAULT_TIMEFRAME_BY_ASSET_CLASS = {"crypto": "4h", "equity": "1d"}
_DEFAULT_N_GROUPS = 10
_CROSS_SECTIONAL_WARMUP_DAYS = 400


def _today_plus_one() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")


def _refresh_start_str(since_timestamp: Any) -> str:
    """Refresh from a run's own data cutoff (minus a small overlap buffer for
    bar revisions), not a fixed recent window. refresh_symbol/refresh_universe
    default to only fetching the last MONITOR_REFRESH_LOOKBACK_DAYS when no
    start is given - fine for a run checked the day after it was created, but
    a run whose data is months old would then only get its most recent ~10
    days refreshed, leaving a silent gap between since_timestamp and that
    fixed window while still claiming to report "since creation"."""
    ts = pd.Timestamp(since_timestamp)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    start = ts - pd.Timedelta(days=MONITOR_REFRESH_LOOKBACK_DAYS)
    return start.strftime("%Y-%m-%d")


def _refresh_and_recompute(run_id: str, conn: duckdb.DuckDBPyConnection, refresh_start: str) -> tuple[str, Any]:
    """Refreshes a single-symbol or cross-sectional run's data (from
    `refresh_start`, see _refresh_start_str, through today) and re-executes
    its own compute() over the merged (historical + fresh) series. Returns a
    ("cross_sectional", CrossSectionalBacktestResult) or ("single",
    BacktestResult) tagged pair rather than unwrapping to just `.returns`, so
    callers that need more than the return series (e.g. GAP 5.3 signal
    export wants the cross-sectional path's `.weights`) don't have to
    duplicate this refresh+recompute logic - refresh_and_backtest and
    refresh_and_recompute_weights below both just unwrap what they need from
    the same call. Raises if the run has no signal.py (e.g. a portfolio run)
    or is missing the config fields needed to know what to refresh."""
    config = run_reader.read_config(run_id) or {}
    run_dir = run_reader.run_dir_for(run_id)
    signal_path = run_dir / "signal.py"
    if not signal_path.exists():
        raise ValueError(f"{run_id} has no signal.py - not a single-symbol or cross-sectional run")
    code = extract_compute_source(signal_path.read_text(encoding="utf-8"))

    universe_cfg = config.get("universe")
    if universe_cfg:
        symbols = [str(s) for s in (universe_cfg.get("symbols") or [])]
        if not symbols:
            raise ValueError(f"{run_id} config.universe has no symbols")
        asset_class = str(universe_cfg.get("asset_class") or "equity")
        timeframe = _DEFAULT_TIMEFRAME_BY_ASSET_CLASS.get(asset_class, "1d")
        refresh_universe(symbols, timeframe, asset_class=asset_class, start=refresh_start, conn=conn)

        original = run_reader.read_returns_series(run_id)
        if original is not None and len(original):
            earliest = original.index.min()
        else:
            earliest = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=_CROSS_SECTIONAL_WARMUP_DAYS)
        start = (earliest - pd.Timedelta(days=_CROSS_SECTIONAL_WARMUP_DAYS)).strftime("%Y-%m-%d")
        panel = query_universe_ohlcv(conn, symbols, start, _today_plus_one())
        if panel.empty:
            raise ValueError(f"no warehouse data available for {run_id}'s universe after refresh")

        factor_values = run_signal_code_panel(code, panel)
        backtest = run_cross_sectional_backtest(
            panel, None, n_groups=_DEFAULT_N_GROUPS, cost_bps=DEFAULT_COST_BPS, factor_values=factor_values
        )
        return "cross_sectional", backtest

    fetch_params = config.get("fetch_params") or {}
    symbol = fetch_params.get("symbol")
    timeframe = fetch_params.get("timeframe", "1d")
    if not symbol:
        raise ValueError(f"{run_id} has no config.fetch_params.symbol - too old to monitor, or not single-symbol")
    data_path = config.get("data_path")
    if not data_path or not Path(data_path).exists():
        raise ValueError(f"{run_id}'s cached source data file is missing - cannot re-run for monitoring")

    old_df = pd.read_parquet(data_path)
    refreshed = refresh_symbol(symbol, timeframe, start=refresh_start, conn=conn)
    new_df = refreshed["df"]
    merged = (
        pd.concat([old_df, new_df], ignore_index=True)
        .drop_duplicates(subset="timestamp", keep="last")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    signal = run_signal_code(code, merged)
    backtest = run_vectorized_backtest(merged, signal, cost_bps=DEFAULT_COST_BPS)
    return "single", backtest


def refresh_and_backtest(run_id: str, conn: duckdb.DuckDBPyConnection, refresh_start: str) -> pd.Series:
    """Refreshes and recomputes run_id (see _refresh_and_recompute), returning
    just the full net-return series (not sliced to "since creation" - callers
    decide the window). Public (not prefixed with _) because it is the shared
    "refresh + recompute" primitive for both decay monitoring (check_run_decay,
    below) and paper tracking (quantbench/factors/paper_tracking.py)."""
    _, backtest = _refresh_and_recompute(run_id, conn, refresh_start)
    return backtest.returns


def refresh_and_recompute_weights(run_id: str, conn: duckdb.DuckDBPyConnection) -> pd.Series | None:
    """Refreshes run_id's cross-sectional data through today and returns the
    latest period's target weight vector (GAP 5.3 signal export). Returns
    None for a single-symbol run - "target weights across a universe" isn't a
    meaningful concept for a one-symbol position, so callers should surface a
    structured "not supported for this factor" response rather than treating
    this as an error.

    refresh_start is computed the same way check_run_decay computes it (from
    the run's own last known data point, via _refresh_start_str) rather than
    from "today" - the goal is fresh current-day data, not a window starting
    in the future, which would fetch nothing."""
    original_returns = run_reader.read_returns_series(run_id)
    if original_returns is not None and len(original_returns):
        refresh_start = _refresh_start_str(original_returns.index.max())
    else:
        refresh_start = _refresh_start_str(pd.Timestamp.now(tz="UTC"))
    kind, backtest = _refresh_and_recompute(run_id, conn, refresh_start)
    if kind != "cross_sectional" or backtest.weights.empty:
        return None
    return backtest.weights.iloc[-1]


def _check_portfolio_decay(
    run_id: str,
    manifest: dict[str, Any],
    config: dict[str, Any],
    conn: duckdb.DuckDBPyConnection,
) -> DecayReport:
    run_dir = run_reader.run_dir_for(run_id)
    weights_path = run_dir / "portfolio_weights.json"
    if not weights_path.exists():
        raise ValueError(f"{run_id} has no portfolio_weights.json")
    weights: dict[str, float] = json.loads(weights_path.read_text(encoding="utf-8"))
    constituent_ids = list(config.get("constituent_run_ids") or list(weights.keys()))

    original_returns = run_reader.read_returns_series(run_id)
    if original_returns is None or original_returns.empty:
        raise ValueError(f"{run_id} has no backtest_result.json returns")
    since_timestamp = original_returns.index.max()
    original_sharpe = float((manifest.get("metrics") or {}).get("sharpe", 0.0))
    refresh_start = _refresh_start_str(since_timestamp)

    constituent_series: dict[str, pd.Series] = {}
    skipped: list[str] = []
    for constituent_id in constituent_ids:
        try:
            constituent_series[constituent_id] = refresh_and_backtest(constituent_id, conn, refresh_start)
        except Exception:
            # One constituent failing to refresh (e.g. it was itself deleted,
            # or is a nested portfolio run) shouldn't block the whole
            # portfolio's decay check - combine() already tolerates weight
            # keys with no matching column.
            skipped.append(constituent_id)
    if not constituent_series:
        raise ValueError(f"none of {run_id}'s {len(constituent_ids)} constituent run(s) could be refreshed")

    returns_df = pd.DataFrame(constituent_series)
    combined = combine(returns_df, weights, cost_bps=DEFAULT_COST_BPS)
    recent = combined.returns[combined.returns.index > since_timestamp]
    report = compute_decay_report(original_sharpe, recent, since_timestamp)
    if skipped:
        report = DecayReport(
            **{
                **report.to_dict(),
                "detail": report.detail + f" ({len(skipped)}/{len(constituent_ids)} constituents could not be refreshed.)",
            }
        )
    return report


def _is_portfolio_run(run_id: str, config: dict[str, Any]) -> bool:
    if config.get("constituent_run_ids"):
        return True
    return (run_reader.run_dir_for(run_id) / "portfolio_weights.json").exists()


def _record_report(run_id: str, report: DecayReport) -> None:
    run_dir = run_reader.run_dir_for(run_id)
    history_path = run_dir / "monitoring_report.json"
    history: list[dict[str, Any]] = []
    if history_path.exists():
        history = json.loads(history_path.read_text(encoding="utf-8"))
    history.append(report.to_dict())
    history_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["live_monitoring"] = {
        "status": report.status,
        "checked_at": report.checked_at,
        "sharpe_decay_ratio": report.sharpe_decay_ratio,
        "recent_sharpe": report.recent_sharpe,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def check_run_decay(run_id: str, conn: duckdb.DuckDBPyConnection | None = None) -> dict[str, Any]:
    """Deterministic, no-LLM decay check for one run. Writes to the run's own
    monitoring_report.json/manifest.json rather than creating a new run because
    repeated health checks are not new research findings.
    """
    own_conn = conn is None
    conn = conn or get_connection()
    try:
        manifest = run_reader.read_manifest(run_id)
        if manifest is None:
            return {"error": f"run {run_id} not found or not finalized"}
        verdict = (manifest.get("review") or {}).get("verdict")
        if verdict not in ALIVE_VERDICTS:
            return {"skipped": "only STRONG/PROMISING runs are monitored", "verdict": verdict}

        config = run_reader.read_config(run_id) or {}
        try:
            if _is_portfolio_run(run_id, config):
                report = _check_portfolio_decay(run_id, manifest, config, conn)
            else:
                original_returns = run_reader.read_returns_series(run_id)
                if original_returns is None or original_returns.empty:
                    return {"error": f"run {run_id} has no backtest_result.json returns"}
                since_timestamp = original_returns.index.max()
                original_sharpe = float((manifest.get("metrics") or {}).get("sharpe", 0.0))
                full_returns = refresh_and_backtest(run_id, conn, _refresh_start_str(since_timestamp))
                recent = full_returns[full_returns.index > since_timestamp]
                report = compute_decay_report(original_sharpe, recent, since_timestamp)
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}

        _record_report(run_id, report)
        return report.to_dict()
    finally:
        if own_conn:
            conn.close()


def run_monitor_pass() -> list[dict[str, Any]]:
    """Checks every STRONG/PROMISING run in runs/. Used by both `monitor
    watch`'s poll loop and `monitor check --all-alive`."""
    conn = get_connection()
    results: list[dict[str, Any]] = []
    try:
        for run_id in run_reader.list_run_ids():
            manifest = run_reader.read_manifest(run_id)
            if manifest is None:
                continue
            verdict = (manifest.get("review") or {}).get("verdict")
            if verdict not in ALIVE_VERDICTS:
                continue
            result = check_run_decay(run_id, conn=conn)
            results.append({"run_id": run_id, **result})
    finally:
        conn.close()
    return results
