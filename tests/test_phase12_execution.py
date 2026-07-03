import pandas as pd


def test_vectorized_backtest_supports_open_next_execution():
    from quantbench.engine.vectorized_backtest import ExecutionConfig, run_vectorized_backtest

    timestamps = pd.date_range("2024-01-01", periods=25, freq="1D", tz="UTC")
    open_prices = [100.0] * 25
    close_prices = [100.0] * 25
    open_prices[21] = 120.0
    close_prices[21] = 132.0
    df = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": open_prices,
            "close": close_prices,
        }
    )
    signal = pd.Series([10.0] * len(df))

    close_t = run_vectorized_backtest(df, signal, cost_bps=0, execution=ExecutionConfig(fill_price="close_t"))
    open_next = run_vectorized_backtest(df, signal, cost_bps=0, execution=ExecutionConfig(fill_price="open_t+1"))

    assert close_t.execution.fill_price == "close_t"
    assert open_next.execution.fill_price == "open_t+1"
    assert round(float(close_t.returns.iloc[20]), 6) == -0.32
    assert round(float(open_next.returns.iloc[20]), 6) == -0.10
    assert open_next.to_json_dict()["execution"]["fill_price"] == "open_t+1"


def test_cross_sectional_backtest_open_next_execution_uses_next_open_to_close_return():
    from quantbench.engine.cross_sectional_backtest import ExecutionConfig, run_cross_sectional_backtest

    timestamps = pd.date_range("2024-01-01", periods=3, freq="1D", tz="UTC")
    rows = []
    specs = {
        "WIN": {"open": [100.0, 100.0, 100.0], "close": [100.0, 100.0, 110.0], "score": 2.0},
        "LOS": {"open": [100.0, 100.0, 100.0], "close": [100.0, 100.0, 90.0], "score": 1.0},
    }
    for symbol, spec in specs.items():
        for i, timestamp in enumerate(timestamps):
            rows.append(
                {
                    "symbol": symbol,
                    "timestamp": timestamp,
                    "open": spec["open"][i],
                    "high": max(spec["open"][i], spec["close"][i]),
                    "low": min(spec["open"][i], spec["close"][i]),
                    "close": spec["close"][i],
                    "volume": 1000,
                }
            )
    panel = pd.DataFrame(rows)

    def compute(df):
        return pd.Series(specs[df["symbol"].iloc[0]]["score"], index=df.index)

    result = run_cross_sectional_backtest(
        panel,
        compute,
        n_groups=2,
        cost_bps=0,
        execution=ExecutionConfig(fill_price="open_t+1"),
    )

    assert round(float(result.returns.iloc[1]), 6) == 0.2
    assert result.to_json_dict()["execution"]["fill_price"] == "open_t+1"


def test_vectorized_backtest_close_next_execution_shifts_fill_by_one_bar():
    from quantbench.engine.vectorized_backtest import ExecutionConfig, run_vectorized_backtest

    timestamps = pd.date_range("2024-01-01", periods=25, freq="1D", tz="UTC")
    close_prices = [100.0] * 25
    close_prices[22] = 110.0
    df = pd.DataFrame({"timestamp": timestamps, "close": close_prices})
    signal = pd.Series([10.0] * len(df))

    close_t = run_vectorized_backtest(df, signal, cost_bps=0, execution=ExecutionConfig(fill_price="close_t"))
    close_next = run_vectorized_backtest(df, signal, cost_bps=0, execution=ExecutionConfig(fill_price="close_t+1"))

    # A signal at t filled at close_{t+1} earns the close_{t+1}->close_{t+2} move,
    # i.e. the same move the close_t convention attributes to t+1.
    assert round(float(close_next.returns.iloc[20]), 6) == round(float(close_t.returns.iloc[21]), 6) == -0.10
    assert round(float(close_next.returns.iloc[21]), 6) == round(float(close_t.returns.iloc[22]), 6)
    assert close_next.execution.fill_price == "close_t+1"
