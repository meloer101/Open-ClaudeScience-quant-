import pandas as pd


def _ohlcv(n=5):
    idx = pd.date_range("2024-01-01", periods=n, freq="1D", tz="UTC")
    return pd.DataFrame({"timestamp": idx, "open": 1.0, "high": 1.1, "low": 0.9, "close": 1.0, "volume": 100.0})


def test_provider_result_defaults_covers_delisted_false():
    from quantbench.data.providers.base import ProviderResult

    result = ProviderResult(df=_ohlcv(), source="fake")
    assert result.covers_delisted is False


def test_apply_covers_delisted_updates_universe_and_is_a_noop_otherwise():
    from quantbench.data.universe import UniverseDefinition, apply_covers_delisted

    universe = UniverseDefinition(
        name="test",
        as_of_date="2024-01-01",
        symbols=["AAA"],
        point_in_time=False,
        survivorship_bias_note="",
        source="test",
    )
    assert universe.covers_delisted is False

    updated = apply_covers_delisted(universe, {"covers_delisted": True})
    assert updated.covers_delisted is True
    assert updated is not universe

    unchanged = apply_covers_delisted(universe, {"covers_delisted": False})
    assert unchanged is universe  # true no-op: same object, not just equal


def test_fetch_universe_ohlcv_aggregates_covers_delisted_conservatively(tmp_path, monkeypatch):
    from quantbench.data import warehouse
    from quantbench.data.universe import UniverseDefinition

    monkeypatch.setattr(warehouse, "DATA_CACHE_DIR", tmp_path / "data_cache")

    def fake_fetch_ohlcv(symbol, timeframe, start, end):
        path = tmp_path / f"{symbol}.parquet"
        df = _ohlcv()
        df.to_parquet(path, index=False)
        covers = symbol != "PARTIAL"
        return path, df, {"provider": "fake", "source": "fake", "covers_delisted": covers}

    monkeypatch.setattr(warehouse, "fetch_ohlcv", fake_fetch_ohlcv)

    conn = warehouse.get_connection(tmp_path / "wh.duckdb")

    all_covered = UniverseDefinition(
        name="all_covered", as_of_date="2024-01-01", symbols=["AAA", "BBB"],
        point_in_time=False, survivorship_bias_note="", source="test",
    )
    _, meta = warehouse.fetch_universe_ohlcv(all_covered, "1d", "2024-01-01", "2024-01-06", conn=conn)
    assert meta["covers_delisted"] is True

    partial = UniverseDefinition(
        name="partial", as_of_date="2024-01-01", symbols=["AAA", "PARTIAL"],
        point_in_time=False, survivorship_bias_note="", source="test",
    )
    _, meta = warehouse.fetch_universe_ohlcv(partial, "1d", "2024-01-01", "2024-01-06", conn=conn)
    assert meta["covers_delisted"] is False


def test_fetch_universe_ohlcv_treats_any_fetch_failure_as_not_covered(tmp_path, monkeypatch):
    from quantbench.data import warehouse
    from quantbench.data.universe import UniverseDefinition

    monkeypatch.setattr(warehouse, "DATA_CACHE_DIR", tmp_path / "data_cache")

    def fake_fetch_ohlcv(symbol, timeframe, start, end):
        if symbol == "BROKEN":
            raise ValueError("no data")
        path = tmp_path / f"{symbol}.parquet"
        df = _ohlcv()
        df.to_parquet(path, index=False)
        return path, df, {"provider": "fake", "source": "fake", "covers_delisted": True}

    monkeypatch.setattr(warehouse, "fetch_ohlcv", fake_fetch_ohlcv)

    conn = warehouse.get_connection(tmp_path / "wh.duckdb")
    universe = UniverseDefinition(
        name="test", as_of_date="2024-01-01", symbols=["AAA", "BROKEN"],
        point_in_time=False, survivorship_bias_note="", source="test",
    )

    _, meta = warehouse.fetch_universe_ohlcv(universe, "1d", "2024-01-01", "2024-01-06", conn=conn)

    assert meta["failed"]
    assert meta["covers_delisted"] is False
