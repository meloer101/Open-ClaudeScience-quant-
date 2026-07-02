import pandas as pd


def test_periods_per_year_uses_observed_bar_density_not_calendar_gap():
    """Regression test: annualizing off the median inter-bar time delta silently
    inflates Sharpe/return for market-hours-only assets, because weekends make
    the typical gap look the same as a continuously-traded asset's gap even
    though far fewer bars actually occur per year."""
    from quantbench.engine.metrics import periods_per_year_from_timestamps

    equity_daily = pd.bdate_range("2022-01-01", "2024-01-01", tz="UTC")
    ppy_equity = periods_per_year_from_timestamps(equity_daily)
    assert 245 <= ppy_equity <= 262, f"expected ~252 trading days/year, got {ppy_equity}"

    crypto_4h = pd.date_range("2022-01-01", "2023-01-01", freq="4h", tz="UTC")
    ppy_crypto = periods_per_year_from_timestamps(crypto_4h)
    assert 2150 <= ppy_crypto <= 2220, f"expected ~2190 4h-bars/year, got {ppy_crypto}"


def _panel() -> pd.DataFrame:
    timestamps = pd.date_range("2024-01-01", periods=5, freq="1D", tz="UTC")
    rows = []
    specs = {
        "WIN": [100, 100, 110, 121, 133.1],
        "MID": [100, 100, 101, 102.01, 103.03],
        "LOS": [100, 100, 90, 81, 72.9],
    }
    for symbol, closes in specs.items():
        for timestamp, close in zip(timestamps, closes, strict=True):
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
    return pd.DataFrame(rows)


def test_cross_sectional_backtest_uses_factor_for_next_period_returns():
    from quantbench.engine.cross_sectional_backtest import run_cross_sectional_backtest

    def compute(df):
        scores = {"WIN": 3.0, "MID": 2.0, "LOS": 1.0}
        return pd.Series(scores[df["symbol"].iloc[0]], index=df.index)

    result = run_cross_sectional_backtest(_panel(), compute, n_groups=3, cost_bps=0)

    assert result.returns.iloc[0] == 0
    assert round(result.returns.iloc[1], 6) == 0.2
    assert result.metrics["rank_ic_mean"] > 0
    assert result.metrics["monotonicity_score"] == 1.0
    assert result.metrics["symbols"] == 3


def test_cross_sectional_backtest_rejects_n_groups_larger_than_available_symbols():
    """Regression: found via a real crypto universe run where 24 of 30
    requested symbols had no data over the date range (young meme-coin
    listings), leaving only 6 symbols against a requested n_groups=10. That
    used to silently degrade into a "0.0 Sharpe / NaN drawdown" result (every
    timestamp's group forced to NaN by _assign_groups) instead of a clear
    error - and in some data shapes surfaced as an opaque numpy TypeError
    deep in the pipeline. The Coordinator's LLM burned ten retries rewriting
    compute() because nothing told it the real problem was
    n_groups-vs-universe-size, not its signal code."""
    from quantbench.engine.cross_sectional_backtest import run_cross_sectional_backtest

    def compute(df):
        scores = {"WIN": 3.0, "MID": 2.0, "LOS": 1.0}
        return pd.Series(scores[df["symbol"].iloc[0]], index=df.index)

    import pytest

    with pytest.raises(ValueError, match=r"n_groups=10 requires at least 10 symbols.*only 3 symbol"):
        run_cross_sectional_backtest(_panel(), compute, n_groups=10, cost_bps=0)


def test_cross_sectional_signal_py_reproduces_real_per_symbol_factor_values(tmp_path, monkeypatch):
    """Regression test for a confirmed bug: running signal.py against panel.parquet
    used to silently mix all symbols together (e.g. pct_change() computed across
    the concatenated long table) instead of applying compute() per symbol, giving
    plausible-looking but wrong numbers with no error. This test would have failed
    before the fix and must keep passing after."""
    import json
    import subprocess
    import sys

    from _fakes import FakeLLMClient

    from quantbench.agent.coordinator import Coordinator
    from quantbench.artifact.store import ArtifactStore

    panel = _panel()

    def fake_fetch_universe_ohlcv(universe, timeframe, start, end):
        return panel, {"symbols_requested": 3, "symbols_fetched": 3, "cache_hits": 0, "failed": {}, "sources": {}}

    monkeypatch.setattr("quantbench.agent.coordinator.fetch_universe_ohlcv", fake_fetch_universe_ohlcv)
    monkeypatch.setattr(
        "quantbench.agent.coordinator.build_universe",
        lambda universe_name, as_of_date, point_in_time=False, limit=None: __import__(
            "quantbench.data.universe", fromlist=["UniverseDefinition"]
        ).UniverseDefinition(
            name="tiny",
            as_of_date=as_of_date,
            symbols=["WIN", "MID", "LOS"],
            point_in_time=False,
            survivorship_bias_note="test",
            source="unit-test",
        ),
    )

    signal_code = "def compute(df):\n    return df['close'].pct_change(1).fillna(0.0)\n"
    script = [
        ("tools", [("build_universe", {"universe_name": "sp500", "as_of_date": "2024-01-01"})]),
        (
            "tools",
            [("run_cross_sectional_backtest", {"code": signal_code, "start": "2024-01-01", "end": "2024-01-06", "n_groups": 3, "cost_bps": 0})],
        ),
        ("text", "done"),
    ]
    coordinator = Coordinator(run_store=ArtifactStore(tmp_path / "runs"), llm=FakeLLMClient(script))
    result = coordinator.run("测试一个简单动量因子的截面表现")

    config = __import__("yaml").safe_load((result.run_dir / "config.yaml").read_text(encoding="utf-8"))
    assert config["data_path"] == str(result.run_dir / "panel.parquet")

    # Phase 4 regression: the cross-sectional path used to save its backtest
    # result as "cross_sectional_backtest_result.json" - a different filename
    # than the single-symbol path's "backtest_result.json" - which silently
    # broke every reader that assumes one canonical name (ChartsPanel,
    # library/compare.py's compute_returns_correlation()). Must stay unified.
    assert (result.run_dir / "backtest_result.json").exists()
    assert not (result.run_dir / "cross_sectional_backtest_result.json").exists()

    output_csv = tmp_path / "standalone_output.csv"
    completed = subprocess.run(
        [sys.executable, str(result.run_dir / "signal.py"), config["data_path"], "--output", str(output_csv)],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    reproduced = pd.read_csv(output_csv, parse_dates=["timestamp"])

    # Independently compute what each symbol's signal *should* be, applying
    # compute() per symbol exactly as the real backtest does.
    expected_frames = []
    for symbol, symbol_df in panel.groupby("symbol", sort=False):
        symbol_df = symbol_df.sort_values("timestamp").reset_index(drop=True)
        expected_frames.append(
            pd.DataFrame(
                {
                    "timestamp": symbol_df["timestamp"],
                    "symbol": symbol,
                    "signal": symbol_df["close"].pct_change(1).fillna(0.0),
                }
            )
        )
    expected = pd.concat(expected_frames, ignore_index=True).sort_values(["timestamp", "symbol"]).reset_index(drop=True)
    reproduced = reproduced.sort_values(["timestamp", "symbol"]).reset_index(drop=True)

    pd.testing.assert_frame_equal(reproduced, expected, check_dtype=False)


def test_data_quality_reports_missing_gaps_drops_and_jumps():
    from quantbench.data.universe import UniverseDefinition
    from quantbench.skills.data_quality import validate_universe_data

    universe = UniverseDefinition(
        name="test",
        as_of_date="2024-01-10",
        symbols=["AAA", "BBB", "CCC"],
        point_in_time=False,
        survivorship_bias_note="biased",
        source="unit",
    )
    panel = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA", "BBB", "BBB"],
            "timestamp": pd.to_datetime(["2024-01-01", "2024-01-03", "2024-01-01", "2024-01-02"], utc=True),
            "open": [10, 30, 10, 10],
            "high": [10, 30, 10, 10],
            "low": [10, 30, 10, 10],
            "close": [10, 30, 10, 10],
            "volume": [1, 1, 1, 1],
        }
    )

    report = validate_universe_data(panel, universe, end="2024-01-20")

    assert report.symbols_missing_entirely == ["CCC"]
    assert report.symbols_with_gaps["AAA"] == 1
    assert "AAA" in report.symbols_delisted_or_dropped
    assert report.suspicious_price_jumps["AAA"] == ["2024-01-03"]
