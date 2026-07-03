import pandas as pd


def test_neutralize_factor_removes_cross_sectional_size_exposure():
    from quantbench.engine.neutralize import neutralize_factor

    timestamps = pd.date_range("2024-01-01", periods=2, freq="1D", tz="UTC")
    rows = []
    sizes = {"A": 1.0, "B": 2.0, "C": 3.0, "D": 4.0}
    for timestamp in timestamps:
        for symbol, size in sizes.items():
            rows.append({"timestamp": timestamp, "symbol": symbol, "factor": 10.0 * size + 5.0, "forward_return": 0.0})
    panel = pd.DataFrame(rows)
    log_size = pd.Series(sizes)

    neutralized = neutralize_factor(panel, dimensions=["size"], log_size=log_size)

    assert neutralized["neutralized"].all()
    assert neutralized["factor"].abs().max() < 1e-10


def test_neutralize_factor_skips_when_cross_section_has_too_few_symbols():
    from quantbench.engine.neutralize import neutralize_factor

    panel = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2024-01-01", "2024-01-01"], utc=True),
            "symbol": ["A", "B"],
            "factor": [1.0, 2.0],
        }
    )

    neutralized = neutralize_factor(panel, dimensions=["size"], log_size=pd.Series({"A": 1.0, "B": 2.0}))

    assert not neutralized["neutralized"].any()
    assert neutralized["factor"].tolist() == [1.0, 2.0]


def _pure_beta_panel(n_periods=40):
    import numpy as np

    timestamps = pd.date_range("2024-01-01", periods=n_periods, freq="1D", tz="UTC")
    betas = {"A": 0.5, "B": 1.0, "C": 1.5, "D": 2.0}
    market = np.resize([0.01, -0.01, 0.02, -0.005], n_periods)
    market[0] = 0.0
    rows = []
    for symbol, beta in betas.items():
        price = 100.0
        for i, timestamp in enumerate(timestamps):
            price *= 1.0 + beta * market[i]
            rows.append(
                {
                    "timestamp": timestamp,
                    "symbol": symbol,
                    "close": price,
                    "factor": 3.0 * beta - 1.0,
                    "forward_return": 0.0,
                }
            )
    return pd.DataFrame(rows), betas


def test_neutralize_factor_removes_pure_beta_exposure():
    from quantbench.engine.neutralize import neutralize_factor, rolling_betas

    panel, _ = _pure_beta_panel()
    betas = rolling_betas(panel)

    neutralized = neutralize_factor(panel, dimensions=["beta"], betas=betas)

    late = neutralized[neutralized["timestamp"] >= panel["timestamp"].unique()[25]]
    assert late["neutralized"].all()
    assert late["factor"].abs().max() < 1e-8


def test_neutralize_factor_requires_betas_when_beta_dimension_requested():
    import pytest

    from quantbench.engine.neutralize import neutralize_factor

    panel, _ = _pure_beta_panel(n_periods=5)
    with pytest.raises(ValueError, match="beta neutralization"):
        neutralize_factor(panel, dimensions=["beta"], betas=None)


def test_rolling_betas_recovers_relative_betas():
    from quantbench.engine.neutralize import rolling_betas

    panel, true_betas = _pure_beta_panel()
    betas = rolling_betas(panel)

    last_ts = panel["timestamp"].max()
    estimated = {symbol: betas.get((last_ts, symbol)) for symbol in true_betas}
    # The equal-weight market proxy rescales betas by a common constant, so
    # check ratios rather than levels.
    ratio = estimated["D"] / estimated["A"]
    assert abs(ratio - true_betas["D"] / true_betas["A"]) < 1e-6


def test_cross_sectional_backtest_beta_neutralization_is_wired():
    from quantbench.engine.cross_sectional_backtest import run_cross_sectional_backtest

    panel, betas = _pure_beta_panel()
    panel = panel.drop(columns=["factor", "forward_return"])
    panel["open"] = panel["close"]
    panel["high"] = panel["close"]
    panel["low"] = panel["close"]
    panel["volume"] = 1000.0

    def compute(df):
        return pd.Series(3.0 * betas[df["symbol"].iloc[0]] - 1.0, index=df.index)

    result = run_cross_sectional_backtest(panel, compute, n_groups=2, cost_bps=0, neutralize=["beta"])

    neutralized_rows = result.factor_panel[result.factor_panel["neutralized"]]
    assert not neutralized_rows.empty
    assert neutralized_rows["factor"].abs().max() < 1e-8
