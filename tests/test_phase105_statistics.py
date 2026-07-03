import numpy as np
import pandas as pd


def test_cpcv_reports_combinatorial_oos_paths_and_purge_width():
    from quantbench.review.cpcv import run_cpcv

    index = pd.date_range("2021-01-01", periods=120, freq="1D", tz="UTC")
    returns = pd.Series(np.random.default_rng(7).normal(0.001, 0.01, len(index)), index=index)

    result = run_cpcv(returns, n_groups=6, lookback_bars=7, embargo_frac=0.05)

    assert result.n_paths == 20  # C(6, 3)
    assert result.n_groups == 6
    assert result.purge_bars == 7
    assert result.embargo_bars == 6  # ceil(0.05 * 120)
    assert len(result.path_test_sharpes) == 20
    assert result.p05_test_sharpe <= result.median_test_sharpe
    assert 0.0 <= result.positive_path_share <= 1.0


def test_cpcv_purge_drops_boundary_periods_and_changes_oos_sharpe():
    """The whole point of the 'P' in CPCV: widening the purge must actually move
    the OOS distribution. Here the periods adjacent to each train/test boundary
    carry an injected positive spike; purging them removes that boundary bonus and
    lowers the median OOS Sharpe. If purge were inert (the earlier bug) these two
    runs would be identical."""
    from quantbench.review.cpcv import run_cpcv

    index = pd.date_range("2022-01-01", periods=180, freq="1D", tz="UTC")
    rng = np.random.default_rng(11)
    values = rng.normal(0.0, 0.01, len(index))
    # Inject a strong positive return at every group boundary - exactly the
    # periods a wide purge window is meant to discard.
    for boundary in np.linspace(0, len(index), 7, dtype=int)[1:-1]:
        for offset in range(-3, 4):
            position = int(boundary) + offset
            if 0 <= position < len(index):
                values[position] = 0.08
    returns = pd.Series(values, index=index)

    without_purge = run_cpcv(returns, n_groups=6, lookback_bars=0, embargo_frac=0.0)
    with_purge = run_cpcv(returns, n_groups=6, lookback_bars=8, embargo_frac=0.05)

    assert without_purge.n_paths == with_purge.n_paths == 20
    assert with_purge.path_test_sharpes != without_purge.path_test_sharpes
    assert with_purge.median_test_sharpe < without_purge.median_test_sharpe


def test_run_review_adds_cpcv_warning_when_most_paths_are_non_positive():
    from quantbench.review import run_review

    index = pd.date_range("2021-01-01", periods=300, freq="1D", tz="UTC")
    # Persistently negative drift -> every combinatorial OOS path is non-positive.
    returns = pd.Series(np.random.default_rng(31).normal(-0.002, 0.01, len(index)), index=index)
    data = pd.DataFrame({"timestamp": index, "close": 100 * (1 + returns).cumprod()})

    report = run_review(
        code="def compute(df):\n    return df['close'].pct_change(20).fillna(0.0)\n",
        returns=returns,
        cost_bps=0,
        rerun_at_cost=lambda bps: {"sharpe": 0.2},
        rerun_with_code=lambda candidate: {"sharpe": 0.2},
        out_of_sample_data=data,
        run_on_data=lambda frame: {"sharpe": -1.0},
        benchmark_returns=None,
        turnover_annual=10,
    )

    cpcv = next(finding for finding in report.findings if finding.check == "cpcv")
    assert cpcv.severity == "warning"
    assert cpcv.detail["lookback_source"] == "inferred"
    assert cpcv.detail["purge_bars"] == 20
    assert cpcv.detail["positive_path_share"] == 0.0
    assert report.verdict in {"PROMISING", "WEAK"}


def test_ic_newey_west_reduces_t_stat_for_autocorrelated_ic_series():
    from quantbench.engine.metrics import ic_newey_west

    rng = np.random.default_rng(4)
    values = []
    current = 0.05
    for _ in range(160):
        current = 0.92 * current + rng.normal(0.01, 0.02)
        values.append(current)
    series = pd.Series(values)
    naive_t = float(series.mean() / series.std(ddof=1) * np.sqrt(len(series)))

    result = ic_newey_west(series)

    assert result.n_periods == len(series)
    assert result.nw_lags > 0
    assert abs(result.t_stat) < abs(naive_t)
    assert 0.0 <= result.p_value <= 1.0


def test_cross_sectional_backtest_json_includes_ic_significance():
    from quantbench.engine.cross_sectional_backtest import run_cross_sectional_backtest

    timestamps = pd.date_range("2022-01-01", periods=40, freq="1D", tz="UTC")
    rows = []
    for symbol_index, symbol in enumerate(["A", "B", "C", "D", "E", "F"]):
        base = 100 + symbol_index
        for time_index, timestamp in enumerate(timestamps):
            rows.append(
                {
                    "timestamp": timestamp,
                    "symbol": symbol,
                    "close": base + symbol_index * time_index * 0.05 + time_index * 0.01,
                }
            )
    panel = pd.DataFrame(rows)

    result = run_cross_sectional_backtest(
        panel,
        lambda df: pd.Series(np.full(len(df), float(df["close"].iloc[0])), index=df.index),
        n_groups=3,
        cost_bps=0,
    )
    payload = result.to_json_dict()

    assert set(payload["ic_significance"]) >= {
        "ic_mean",
        "ic_std",
        "t_stat",
        "p_value",
        "n_periods",
        "nw_lags",
        "is_significant",
    }


def test_research_note_formats_ic_significance():
    from quantbench.skills.report import _metrics_rows

    rows = _metrics_rows(
        {"rank_ic_mean": 0.031, "sharpe": 1.2},
        ic_significance={"t_stat": 2.4, "p_value": 0.016, "nw_lags": 3, "is_significant": True},
    )

    assert "rank_ic_mean | 0.031 (t=2.4, p=0.016, NW-lags=3)" in rows
