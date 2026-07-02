from __future__ import annotations

from typing import Any

import pandas as pd

from quantbench.api import run_reader


METRIC_FIELDS = ("sharpe", "annual_return", "max_drawdown", "turnover_annual", "ic_mean")

# Below this many overlapping observations, a correlation coefficient is not
# statistically meaningful (and can look wildly high/low by chance). Matches
# the min-observation guards already used by the Reviewer (MIN_OOS_OBSERVATIONS,
# MIN_BETA_OBSERVATIONS in quantbench/review/report.py) rather than inventing a
# new threshold philosophy.
MIN_CORRELATION_OBSERVATIONS = 30


def compare_runs(run_ids: list[str]) -> dict[str, Any]:
    metrics = {field: {} for field in METRIC_FIELDS}
    verdicts: dict[str, str | None] = {}
    findings: dict[str, list[dict[str, Any]]] = {}
    hypotheses: dict[str, str] = {}

    for run_id in run_ids:
        manifest = run_reader.read_manifest(run_id) or {}
        config = run_reader.read_config(run_id) or {}
        run_metrics = manifest.get("metrics") or {}
        review = manifest.get("review") or {}
        hypotheses[run_id] = config.get("hypothesis") or manifest.get("user_request") or run_reader.read_user_request(run_id)
        verdicts[run_id] = review.get("verdict")
        for field in METRIC_FIELDS:
            metrics[field][run_id] = run_metrics.get(field)
        findings[run_id] = [
            finding
            for finding in (review.get("findings") or [])
            if str(finding.get("severity", "")).lower() in {"critical", "warning"}
        ]

    return {"run_ids": run_ids, "hypotheses": hypotheses, "metrics": metrics, "verdicts": verdicts, "findings": findings}


def compute_returns_correlation(run_ids: list[str]) -> dict[str, dict[str, float | None]]:
    """Pairwise Pearson correlation of each run's own return series, aligned by
    timestamp. A cell is null when either run's returns are unavailable or the
    two runs don't share enough overlapping observations to make the
    coefficient meaningful (see MIN_CORRELATION_OBSERVATIONS) - never a
    silently-computed number from too few points."""
    series_by_run = {run_id: _read_returns_series(run_id) for run_id in run_ids}
    matrix: dict[str, dict[str, float | None]] = {run_id: {} for run_id in run_ids}
    for i, run_a in enumerate(run_ids):
        for run_b in run_ids:
            if run_a == run_b:
                matrix[run_a][run_b] = 1.0 if series_by_run[run_a] is not None else None
                continue
            matrix[run_a][run_b] = _correlate(series_by_run[run_a], series_by_run[run_b])
    return matrix


def _read_returns_series(run_id: str) -> pd.Series | None:
    result = run_reader.read_backtest_result(run_id)
    if result is None:
        return None
    series = result.get("series") or {}
    timestamps = series.get("timestamp")
    # Single-symbol runs key their series "returns"; cross-sectional runs key
    # it "long_short_returns" (see CrossSectionalBacktestResult.to_json_dict).
    values = series.get("returns") if "returns" in series else series.get("long_short_returns")
    if not timestamps or not values or len(timestamps) != len(values):
        return None
    return pd.Series(values, index=pd.to_datetime(timestamps, utc=True, errors="coerce")).dropna()


def _correlate(a: pd.Series | None, b: pd.Series | None) -> float | None:
    if a is None or b is None:
        return None
    aligned = pd.concat([a, b], axis=1, join="inner").dropna()
    if len(aligned) < MIN_CORRELATION_OBSERVATIONS:
        return None
    correlation = aligned.iloc[:, 0].corr(aligned.iloc[:, 1])
    return None if pd.isna(correlation) else round(float(correlation), 6)
