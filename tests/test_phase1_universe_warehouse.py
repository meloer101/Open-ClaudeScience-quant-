import pandas as pd


def test_build_sp500_universe_marks_survivorship_bias(monkeypatch):
    from quantbench.data import universe

    monkeypatch.setattr(
        universe,
        "fetch_current_constituents",
        lambda: pd.DataFrame(
            {
                "Symbol": [f"SYM{i}" for i in range(401)],
                "Security": [f"Company {i}" for i in range(401)],
            }
        ),
    )

    result = universe.build_sp500_universe("2026-07-01")

    assert result.name == "sp500"
    assert result.point_in_time is False
    assert len(result.symbols) == 401
    assert "survivorship bias" in result.survivorship_bias_note


def test_build_sp500_universe_limit_truncates_and_flags_non_representative(monkeypatch):
    from quantbench.data import universe

    monkeypatch.setattr(
        universe,
        "fetch_current_constituents",
        lambda: pd.DataFrame(
            {
                "Symbol": [f"SYM{i:03d}" for i in range(500)],
                "Security": [f"Company {i}" for i in range(500)],
            }
        ),
    )

    result = universe.build_sp500_universe("2026-07-01", limit=10)

    assert len(result.symbols) == 10
    assert result.symbols == sorted(f"SYM{i:03d}" for i in range(500))[:10]
    assert result.sample_limit == 10
    assert "NOT representative" in result.survivorship_bias_note


def test_build_sp500_universe_point_in_time_uses_membership_window(monkeypatch):
    from quantbench.data import universe

    def fake_pit(start, end):
        assert start == "2020-01-01"
        assert end == "2021-01-01"
        return ["AAA", "OLD"], {
            "AAA": [("2020-06-01", "2021-01-01")],
            "OLD": [("2020-01-01", "2020-06-01")],
        }

    monkeypatch.setattr(universe, "build_point_in_time_sp500", fake_pit, raising=False)

    result = universe.build_sp500_universe(
        "2021-01-01",
        point_in_time=True,
        start="2020-01-01",
        end="2021-01-01",
    )

    assert result.point_in_time is True
    assert result.symbols == ["AAA", "OLD"]
    assert result.membership_intervals == {
        "AAA": [["2020-06-01", "2021-01-01"]],
        "OLD": [["2020-01-01", "2020-06-01"]],
    }
    assert result.covers_delisted is False
    assert "point-in-time" in result.survivorship_bias_note


def test_build_sp500_universe_point_in_time_requires_window():
    import pytest

    from quantbench.data import universe

    with pytest.raises(ValueError, match="start and end"):
        universe.build_sp500_universe("2021-01-01", point_in_time=True)


def test_warehouse_upsert_replaces_symbol_timestamp_rows(tmp_path):
    from quantbench.data.warehouse import get_connection, query_universe_ohlcv, upsert_ohlcv

    conn = get_connection(tmp_path / "warehouse.duckdb")
    original = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-01", periods=2, freq="1D", tz="UTC"),
            "open": [10.0, 11.0],
            "high": [10.5, 11.5],
            "low": [9.5, 10.5],
            "close": [10.25, 11.25],
            "volume": [100, 110],
        }
    )
    updated = original.copy()
    updated.loc[0, "close"] = 99.0

    upsert_ohlcv(conn, "AAA", original, provider="fake", source="unit")
    upsert_ohlcv(conn, "AAA", updated, provider="fake", source="unit")
    result = query_universe_ohlcv(conn, ["AAA"], "2024-01-01", "2024-01-03")

    assert len(result) == 2
    assert result.loc[result["timestamp"] == pd.Timestamp("2024-01-01", tz="UTC"), "close"].iloc[0] == 99.0


def test_pit_coverage_report_counts_missing_member_bars():
    from quantbench.data.universe import UniverseDefinition
    from quantbench.data.warehouse import universe_coverage_report

    universe = UniverseDefinition(
        name="sp500",
        as_of_date="2024-01-05",
        symbols=["AAA", "OLD"],
        point_in_time=True,
        survivorship_bias_note="pit",
        source="unit",
        membership_intervals={
            "AAA": [["2024-01-01", "2024-01-05"]],
            "OLD": [["2024-01-01", "2024-01-05"]],
        },
        covers_delisted=False,
    )
    # The trading calendar is implied by the data itself: AAA trades all five
    # days, so those five days are "expected" for every member. OLD (e.g. a
    # symbol whose data is only partially available) is missing three of them.
    panel = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA", "AAA", "AAA", "AAA", "OLD", "OLD"],
            "timestamp": pd.to_datetime(
                ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-01", "2024-01-02"],
                utc=True,
            ),
            "open": [1.0] * 7,
            "high": [1.0] * 7,
            "low": [1.0] * 7,
            "close": [1.0] * 7,
            "volume": [1.0] * 7,
        }
    )

    report = universe_coverage_report(universe, panel, "2024-01-01", "2024-01-05", timeframe="1d")

    assert report["point_in_time"] is True
    assert report["covers_delisted"] is False
    assert report["expected_member_bars"] == 10  # 5 trading days x 2 members
    assert report["observed_member_bars"] == 7
    assert report["missing_member_bars"] == 3
    assert report["symbols_with_data"] == 2
    assert report["symbols_missing_entirely"] == []
    assert report["per_symbol"]["AAA"]["missing_bars"] == 0
    assert report["per_symbol"]["OLD"]["missing_bars"] == 3
