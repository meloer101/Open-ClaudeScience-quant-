import pandas as pd


def test_liquidity_costs_cap_weights_and_apply_spread_tiers():
    from quantbench.engine.costs import LiquidityCostConfig, apply_liquidity_costs

    dates = pd.date_range("2024-01-01", periods=2, freq="1D", tz="UTC")
    weights = pd.DataFrame({"BIG": [0.5, 0.5], "SMALL": [0.5, 0.5]}, index=dates)
    dollar_volume = pd.DataFrame({"BIG": [1_000_000_000, 1_000_000_000], "SMALL": [100_000, 100_000]}, index=dates)
    config = LiquidityCostConfig(aum_usd=1_000_000, participation_cap=0.02)

    actual, costs = apply_liquidity_costs(weights, dollar_volume, config)

    assert round(float(actual.loc[dates[0], "SMALL"]), 6) == 0.002
    assert round(float(actual.loc[dates[0], "BIG"]), 6) == 0.5
    assert round(float(costs.iloc[0]), 6) == 0.000052
    assert float(costs.iloc[1]) == 0.0


def test_capacity_curve_degrades_when_aum_exceeds_adv_cap():
    from quantbench.engine.costs import LiquidityCostConfig, capacity_curve

    dates = pd.date_range("2024-01-01", periods=4, freq="1D", tz="UTC")
    weights = pd.DataFrame({"SMALL": [1.0, 1.0, 1.0, 1.0]}, index=dates)
    dollar_volume = pd.DataFrame({"SMALL": [100_000, 100_000, 100_000, 100_000]}, index=dates)
    gross = pd.Series([0.02, 0.02, 0.02, 0.02], index=dates)

    curve = capacity_curve(
        gross,
        weights,
        dollar_volume,
        LiquidityCostConfig(participation_cap=0.02),
        aum_grid=(1_000, 1_000_000),
    )

    assert curve[0]["aum_usd"] == 1_000
    assert curve[0]["average_fill_ratio"] == 1.0
    assert curve[1]["average_fill_ratio"] < curve[0]["average_fill_ratio"]
    assert curve[1]["sharpe"] < curve[0]["sharpe"]
