def test_record_and_query_crypto_universe_snapshot_round_trip(tmp_path, monkeypatch):
    from quantbench.data import warehouse

    fake_rows = [
        {"symbol": "BTC/USDT", "quote_volume_24h": 3_000_000_000.0},
        {"symbol": "ETH/USDT", "quote_volume_24h": 1_500_000_000.0},
        {"symbol": "SOL/USDT", "quote_volume_24h": 200_000_000.0},
    ]
    monkeypatch.setattr(
        "quantbench.data.providers.ccxt_perpetual.fetch_top_symbols_by_volume",
        lambda quote="USDT", limit=30: fake_rows,
    )

    conn = warehouse.get_connection(tmp_path / "wh.duckdb")
    written = warehouse.record_crypto_universe_snapshot(conn, "2026-07-05", quote="USDT", limit=30)
    assert written == 3

    symbols = warehouse.query_crypto_universe_snapshot(conn, "2026-07-05")
    assert symbols == ["BTC/USDT", "ETH/USDT", "SOL/USDT"]  # ordered by rank (descending volume)


def test_query_crypto_universe_snapshot_returns_none_for_unsnapshotted_date(tmp_path):
    from quantbench.data import warehouse

    conn = warehouse.get_connection(tmp_path / "wh.duckdb")
    assert warehouse.query_crypto_universe_snapshot(conn, "2020-01-01") is None


def test_record_crypto_universe_snapshot_is_idempotent_on_same_date(tmp_path, monkeypatch):
    from quantbench.data import warehouse

    fake_rows = [{"symbol": "BTC/USDT", "quote_volume_24h": 1.0}]
    monkeypatch.setattr(
        "quantbench.data.providers.ccxt_perpetual.fetch_top_symbols_by_volume",
        lambda quote="USDT", limit=30: fake_rows,
    )

    conn = warehouse.get_connection(tmp_path / "wh.duckdb")
    warehouse.record_crypto_universe_snapshot(conn, "2026-07-05")
    warehouse.record_crypto_universe_snapshot(conn, "2026-07-05")  # re-snapshot same day

    symbols = warehouse.query_crypto_universe_snapshot(conn, "2026-07-05")
    assert symbols == ["BTC/USDT"]


def test_record_crypto_universe_snapshot_handles_no_rows(tmp_path, monkeypatch):
    from quantbench.data import warehouse

    monkeypatch.setattr(
        "quantbench.data.providers.ccxt_perpetual.fetch_top_symbols_by_volume",
        lambda quote="USDT", limit=30: [],
    )

    conn = warehouse.get_connection(tmp_path / "wh.duckdb")
    assert warehouse.record_crypto_universe_snapshot(conn, "2026-07-05") == 0
    assert warehouse.query_crypto_universe_snapshot(conn, "2026-07-05") is None
