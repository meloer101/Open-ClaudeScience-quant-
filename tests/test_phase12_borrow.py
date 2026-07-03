import pandas as pd


def test_borrow_cost_only_charges_short_weights():
    from quantbench.engine.cross_sectional_backtest import _borrow_cost

    dates = pd.date_range("2024-01-01", periods=2, freq="1D", tz="UTC")
    weights = pd.DataFrame({"LONG": [0.5, 0.5], "SHORT": [-0.5, -0.25]}, index=dates)
    borrow_rates = pd.DataFrame({"LONG": [0.10, 0.10], "SHORT": [0.20, 0.20]}, index=dates)

    costs = _borrow_cost(weights, borrow_rates)

    assert round(float(costs.iloc[0]), 6) == 0.1
    assert round(float(costs.iloc[1]), 6) == 0.05


def test_cross_sectional_backtest_reports_short_contribution_share():
    from quantbench.engine.cross_sectional_backtest import run_cross_sectional_backtest

    timestamps = pd.date_range("2024-01-01", periods=4, freq="1D", tz="UTC")
    rows = []
    closes = {"LONG": [100, 100, 101, 102], "SHORT": [100, 100, 90, 81]}
    scores = {"LONG": 2.0, "SHORT": 1.0}
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
                    "volume": 1000,
                }
            )
    panel = pd.DataFrame(rows)

    def compute(df):
        return pd.Series(scores[df["symbol"].iloc[0]], index=df.index)

    result = run_cross_sectional_backtest(panel, compute, n_groups=2, cost_bps=0)

    assert result.long_short_contribution["short_share"] > 0.7
    assert result.to_json_dict()["long_short_contribution"]["short_share"] > 0.7
