import pandas as pd


def test_reviewer_flags_low_capacity_and_short_dependency():
    from quantbench.review import run_review

    dates = pd.date_range("2024-01-01", periods=80, freq="1D", tz="UTC")
    returns = pd.Series([0.01, -0.002] * 40, index=dates)
    df = pd.DataFrame({"timestamp": dates, "close": 100.0})

    report = run_review(
        code="def compute(df):\n    return df['close'].pct_change().fillna(0.0)\n",
        returns=returns,
        cost_bps=0,
        rerun_at_cost=lambda bps: {"sharpe": 1.0},
        rerun_with_code=lambda candidate: {"sharpe": 1.0},
        out_of_sample_data=df,
        run_on_data=lambda data: {"sharpe": 1.0},
        turnover_annual=10,
        capacity_curve=[
            {"aum_usd": 100_000, "sharpe": 2.0, "average_fill_ratio": 1.0},
            {"aum_usd": 500_000, "sharpe": 0.8, "average_fill_ratio": 0.4},
        ],
        long_short_contribution={"long_contribution": 0.1, "short_contribution": 0.5, "short_share": 0.83},
    )

    findings = {finding.check: finding for finding in report.findings}
    assert findings["capacity"].severity == "warning"
    assert findings["short_dependency"].severity == "warning"
    assert report.verdict in {"PROMISING", "WEAK", "REJECTED"}


def test_reviewer_flags_execution_sensitivity_decay():
    from quantbench.review import run_review

    dates = pd.date_range("2024-01-01", periods=80, freq="1D", tz="UTC")
    returns = pd.Series([0.01, -0.002] * 40, index=dates)
    df = pd.DataFrame({"timestamp": dates, "close": 100.0})

    report = run_review(
        code="def compute(df):\n    return df['close'].pct_change().fillna(0.0)\n",
        returns=returns,
        cost_bps=0,
        rerun_at_cost=lambda bps: {"sharpe": 1.0},
        rerun_with_code=lambda candidate: {"sharpe": 1.0},
        out_of_sample_data=df,
        run_on_data=lambda data: {"sharpe": 1.0},
        turnover_annual=10,
        execution_sensitivity={"close_t_sharpe": 1.2, "open_t+1_sharpe": 0.2},
    )

    finding = next(item for item in report.findings if item.check == "execution_sensitivity")
    assert finding.severity == "warning"
