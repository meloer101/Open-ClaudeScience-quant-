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
