import pandas as pd


def _pit_panel() -> pd.DataFrame:
    timestamps = pd.date_range("2024-01-01", periods=5, freq="1D", tz="UTC")
    rows = []
    closes = {
        "WIN": [100, 100, 110, 121, 133.1],
        "MID": [100, 100, 101, 102.01, 103.03],
        "LOS": [100, 100, 90, 81, 72.9],
    }
    for symbol, values in closes.items():
        for timestamp, close in zip(timestamps, values, strict=True):
            rows.append(
                {
                    "symbol": symbol,
                    "timestamp": timestamp,
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1_000,
                }
            )
    return pd.DataFrame(rows)


def test_cross_sectional_backtest_masks_rows_outside_membership_intervals():
    from quantbench.engine.cross_sectional_backtest import run_cross_sectional_backtest

    def compute(df):
        scores = {"WIN": 3.0, "MID": 2.0, "LOS": 1.0}
        return pd.Series(scores[df["symbol"].iloc[0]], index=df.index)

    result = run_cross_sectional_backtest(
        _pit_panel(),
        compute,
        n_groups=2,
        cost_bps=0,
        membership_intervals={
            "WIN": [["2024-01-01", "2024-01-03"]],
            "MID": [["2024-01-01", "2024-01-05"]],
            "LOS": [["2024-01-03", "2024-01-05"]],
        },
    )

    factor_panel = result.factor_panel
    win_dates = factor_panel.loc[factor_panel["symbol"] == "WIN", "timestamp"]
    los_dates = factor_panel.loc[factor_panel["symbol"] == "LOS", "timestamp"]

    assert win_dates.max() <= pd.Timestamp("2024-01-03", tz="UTC")
    assert los_dates.min() >= pd.Timestamp("2024-01-03", tz="UTC")
    assert result.metrics["observations"] == len(factor_panel)


def test_review_warns_and_caps_strong_when_pit_coverage_is_incomplete():
    from quantbench.review.report import run_review

    returns = pd.Series(
        [0.01, -0.002, 0.004, 0.006, -0.001] * 12,
        index=pd.date_range("2024-01-01", periods=60, freq="1D", tz="UTC"),
    )
    data = pd.DataFrame(
        {
            "timestamp": returns.index,
            "close": range(100, 160),
        }
    )

    report = run_review(
        code="def compute(df):\n    return df['close'].pct_change().fillna(0)\n",
        returns=returns,
        cost_bps=0,
        rerun_at_cost=lambda bps: {"sharpe": 1.0},
        rerun_with_code=lambda code: {"sharpe": 1.0},
        out_of_sample_data=data,
        run_on_data=lambda frame: {"sharpe": 1.0},
        universe_coverage={
            "point_in_time": True,
            "covers_delisted": False,
            "expected_member_bars": 100,
            "observed_member_bars": 85,
            "missing_member_bars": 15,
            "missing_rate": 0.15,
            "symbols_expected": 5,
            "symbols_with_data": 4,
            "symbols_missing_entirely": ["OLD"],
        },
    )

    finding = next(item for item in report.findings if item.check == "universe_coverage")
    assert finding.severity == "warning"
    assert "residual survivorship bias" in finding.message
    assert report.verdict != "STRONG"


def test_clean_pit_coverage_is_capped_promising_with_explained_reason():
    from quantbench.review.report import run_review

    returns = pd.Series(
        [0.01, -0.002, 0.004, 0.006, -0.001] * 12,
        index=pd.date_range("2024-01-01", periods=60, freq="1D", tz="UTC"),
    )
    data = pd.DataFrame({"timestamp": returns.index, "close": range(100, 160)})

    report = run_review(
        code="def compute(df):\n    return df['close'].pct_change().fillna(0)\n",
        returns=returns,
        cost_bps=0,
        rerun_at_cost=lambda bps: {"sharpe": 1.0},
        rerun_with_code=lambda code: {"sharpe": 1.0},
        out_of_sample_data=data,
        run_on_data=lambda frame: {"sharpe": 1.0},
        universe_coverage={
            "point_in_time": True,
            "covers_delisted": False,
            "expected_member_bars": 100,
            "observed_member_bars": 100,   # fully covered
            "missing_member_bars": 0,
            "missing_rate": 0.0,
            "symbols_expected": 5,
            "symbols_with_data": 5,
            "symbols_missing_entirely": [],
        },
    )

    finding = next(item for item in report.findings if item.check == "universe_coverage")
    assert finding.severity == "warning"
    assert "by design" in finding.message
    assert "not a factor-quality problem" in finding.message
    # Capped at PROMISING - never STRONG - but not rejected.
    assert report.verdict == "PROMISING"
