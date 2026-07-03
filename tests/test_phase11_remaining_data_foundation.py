import json

import pandas as pd
from click.testing import CliRunner


def test_cross_sectional_backtest_subtracts_funding_by_position_direction():
    from quantbench.engine.cross_sectional_backtest import run_cross_sectional_backtest

    timestamps = pd.date_range("2024-01-01", periods=4, freq="1D", tz="UTC")
    rows = []
    for symbol, closes in {
        "LONG": [100, 110, 121, 133.1],
        "SHORT": [100, 90, 81, 72.9],
    }.items():
        for timestamp, close in zip(timestamps, closes, strict=True):
            rows.append({"symbol": symbol, "timestamp": timestamp, "open": close, "high": close, "low": close, "close": close, "volume": 1})
    panel = pd.DataFrame(rows)
    funding = pd.DataFrame(
        {
            "symbol": ["LONG", "SHORT", "LONG", "SHORT", "LONG", "SHORT"],
            "timestamp": [timestamps[0], timestamps[0], timestamps[1], timestamps[1], timestamps[2], timestamps[2]],
            "funding_rate": [0.01, 0.01, 0.01, 0.01, 0.01, 0.01],
        }
    )

    def compute(df):
        return pd.Series(1.0 if df["symbol"].iloc[0] == "LONG" else 0.0, index=df.index)

    no_funding = run_cross_sectional_backtest(panel, compute, n_groups=2, cost_bps=0)
    with_funding = run_cross_sectional_backtest(panel, compute, n_groups=2, cost_bps=0, funding_rates=funding)

    assert round(no_funding.returns.iloc[0] - with_funding.returns.iloc[0], 6) == 0.0
    assert with_funding.metrics["funding_cost_total"] == 0.0

    funding.loc[funding["symbol"] == "LONG", "funding_rate"] = 0.02
    funding.loc[funding["symbol"] == "SHORT", "funding_rate"] = 0.0
    with_directional_cost = run_cross_sectional_backtest(panel, compute, n_groups=2, cost_bps=0, funding_rates=funding)

    assert round(no_funding.returns.iloc[0] - with_directional_cost.returns.iloc[0], 6) == 0.02
    assert with_directional_cost.metrics["funding_cost_total"] > 0


def test_ccxt_funding_rate_history_normalizes_rows(monkeypatch):
    from quantbench.data.providers import ccxt_perpetual

    class FakeExchange:
        def load_markets(self):
            return {"BTC/USDT:USDT": {"swap": True, "quote": "USDT"}}

        def parse8601(self, value):
            return int(pd.Timestamp(value).timestamp() * 1000)

        def fetch_funding_rate_history(self, symbol, since=None, limit=None):
            assert symbol == "BTC/USDT:USDT"
            return [
                {"timestamp": since, "fundingRate": "0.0001"},
                {"timestamp": since + 8 * 60 * 60 * 1000, "fundingRate": 0.0002},
            ]

    monkeypatch.setattr(ccxt_perpetual, "_build_exchange", lambda: FakeExchange())

    result = ccxt_perpetual.fetch_funding_rate("BTC/USDT", "2024-01-01", "2024-01-02")

    assert result.source.startswith("ccxt_")
    assert result.df.columns.tolist() == ["timestamp", "funding_rate"]
    assert result.df["funding_rate"].tolist() == [0.0001, 0.0002]


def test_provider_result_records_adjustment_metadata():
    from quantbench.data.providers.base import Adjustment, ProviderResult

    result = ProviderResult(
        df=pd.DataFrame(),
        source="unit",
        adjustment=Adjustment(method="raw", dividend_reinvested=False),
    )

    assert result.adjustment.to_dict() == {"method": "raw", "dividend_reinvested": False}


def test_polygon_provider_slot_documents_schema_mapping():
    from quantbench.data.providers.polygon_equity import provider_result_from_rows

    result = provider_result_from_rows(
        [{"t": 1704067200000, "o": 1.0, "h": 2.0, "l": 0.5, "c": 1.5, "v": 100}]
    )

    assert result.df.columns.tolist() == ["timestamp", "open", "high", "low", "close", "volume"]
    assert result.adjustment.to_dict() == {"method": "split_dividend", "dividend_reinvested": False}


def test_rerun_reports_data_drift(tmp_path, monkeypatch):
    from quantbench.cli import main
    from quantbench.config import RUNS_DIR
    from quantbench.data.cache import file_sha256

    run_dir = tmp_path / "runs" / "run_20260703_000000_test"
    cache_file = tmp_path / "slice.parquet"
    run_dir.mkdir(parents=True)
    cache_file.write_text("original", encoding="utf-8")
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_dir.name,
                "data_slices": [
                    {
                        "symbol": "AAA",
                        "timeframe": "1d",
                        "start": "2024-01-01",
                        "end": "2024-02-01",
                        "path": str(cache_file),
                        "content_hash": file_sha256(cache_file),
                        "rows": 10,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    cache_file.write_text("changed", encoding="utf-8")
    monkeypatch.setattr("quantbench.api.run_reader.RUNS_DIR", tmp_path / "runs")

    result = CliRunner().invoke(main, ("rerun", run_dir.name))

    assert result.exit_code != 0
    assert "Data drift detected" in result.output


def _coverage_universe(symbols, intervals):
    from quantbench.data.universe import UniverseDefinition

    return UniverseDefinition(
        name="sp500",
        as_of_date="2024-01-10",
        symbols=symbols,
        point_in_time=True,
        survivorship_bias_note="",
        source="test",
        asset_class="equity",
        membership_intervals=intervals,
        covers_delisted=False,
    )


def _panel(rows_by_symbol):
    rows = []
    for symbol, days in rows_by_symbol.items():
        for day in days:
            ts = pd.Timestamp(day, tz="UTC")
            rows.append({"symbol": symbol, "timestamp": ts, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1})
    return pd.DataFrame(rows)


def test_coverage_uses_observed_trading_calendar_not_business_days():
    # 2024-01-04 is a "holiday": no symbol trades it. It must NOT be counted as a
    # missing bar for the fully-covered symbol.
    from quantbench.data.warehouse import universe_coverage_report

    market_days = ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-05", "2024-01-08", "2024-01-09", "2024-01-10"]
    panel = _panel(
        {
            "STAY": market_days,               # complete
            "GAP": ["2024-01-01", "2024-01-02"],  # trades only 2 of the 7 calendar days
            # DEAD: no rows at all (delisted, data unavailable)
        }
    )
    universe = _coverage_universe(
        ["STAY", "GAP", "DEAD"],
        {
            "STAY": [["2024-01-01", "2024-01-10"]],
            "GAP": [["2024-01-01", "2024-01-10"]],
            "DEAD": [["2024-01-01", "2024-01-05"]],
        },
    )

    report = universe_coverage_report(universe, panel, "2024-01-01", "2024-01-10", timeframe="1d")

    # The holiday (01-04) is not in the observed calendar, so a fully-covered
    # symbol shows 100% coverage - no false "missing" bar.
    assert report["per_symbol"]["STAY"]["coverage"] == 1.0
    assert report["per_symbol"]["STAY"]["missing_bars"] == 0
    # Trading calendar has 7 days; GAP observed only 2 of them.
    assert report["per_symbol"]["GAP"]["expected_bars"] == 7
    assert report["per_symbol"]["GAP"]["observed_bars"] == 2
    # DEAD's interval [01-01, 01-05] covers 4 trading days, none observed.
    assert report["per_symbol"]["DEAD"]["expected_bars"] == 4
    assert report["per_symbol"]["DEAD"]["observed_bars"] == 0
    assert "DEAD" in report["symbols_missing_entirely"]


def test_severe_pit_coverage_gap_is_rejected_not_just_promising():
    from quantbench.review.report import run_review

    returns = pd.Series(
        [0.01, -0.002, 0.004] * 20,
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
            "observed_member_bars": 45,
            "missing_member_bars": 55,
            "missing_rate": 0.55,
            "symbols_expected": 10,
            "symbols_with_data": 5,
            "symbols_missing_entirely": ["A", "B", "C", "D", "E"],
        },
    )

    finding = next(item for item in report.findings if item.check == "universe_coverage")
    assert finding.severity == "critical"
    assert report.verdict == "REJECTED"
