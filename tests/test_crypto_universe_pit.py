import pytest


def test_reconstruct_intervals_symbol_continuously_present():
    from quantbench.data.providers.crypto_universe_history import reconstruct_crypto_membership_intervals

    daily = {
        "2026-01-01": ["A", "B"],
        "2026-01-02": ["A", "B"],
        "2026-01-03": ["A", "B"],
    }
    intervals = reconstruct_crypto_membership_intervals(daily)
    assert intervals["A"] == [("2026-01-01", "2026-01-03")]
    assert intervals["B"] == [("2026-01-01", "2026-01-03")]


def test_reconstruct_intervals_symbol_disappears_then_never_returns():
    from quantbench.data.providers.crypto_universe_history import reconstruct_crypto_membership_intervals

    daily = {
        "2026-01-01": ["A", "B"],
        "2026-01-02": ["B"],
        "2026-01-03": ["B"],
    }
    intervals = reconstruct_crypto_membership_intervals(daily)
    assert intervals["A"] == [("2026-01-01", "2026-01-01")]
    assert intervals["B"] == [("2026-01-01", "2026-01-03")]


def test_reconstruct_intervals_symbol_reappears_after_absence():
    from quantbench.data.providers.crypto_universe_history import reconstruct_crypto_membership_intervals

    daily = {
        "2026-01-01": ["A"],
        "2026-01-02": [],
        "2026-01-03": ["A"],
    }
    intervals = reconstruct_crypto_membership_intervals(daily)
    # Two separate intervals, not one bridging the day it dropped out.
    assert intervals["A"] == [("2026-01-01", "2026-01-01"), ("2026-01-03", "2026-01-03")]


def test_reconstruct_intervals_snapshot_gap_splits_interval_rather_than_bridging():
    from quantbench.data.providers.crypto_universe_history import reconstruct_crypto_membership_intervals

    daily = {
        "2026-01-01": ["A"],
        "2026-01-02": None,  # no snapshot taken that day
        "2026-01-03": ["A"],
    }
    intervals = reconstruct_crypto_membership_intervals(daily)
    # Same shape as the "dropped out" case: the gap in coverage must not be
    # silently assumed to mean "still present."
    assert intervals["A"] == [("2026-01-01", "2026-01-01"), ("2026-01-03", "2026-01-03")]


def test_earliest_snapshot_date_ignores_none_days():
    from quantbench.data.providers.crypto_universe_history import earliest_snapshot_date

    assert earliest_snapshot_date({"2026-01-01": None, "2026-01-02": ["A"], "2026-01-03": ["A"]}) == "2026-01-02"
    assert earliest_snapshot_date({"2026-01-01": None}) is None
    assert earliest_snapshot_date({}) is None


def test_build_point_in_time_crypto_perpetual_raises_without_any_snapshot(tmp_path, monkeypatch):
    from quantbench.data import universe as universe_mod
    from quantbench.data.warehouse import get_connection

    conn = get_connection(tmp_path / "wh.duckdb")

    with pytest.raises(ValueError, match="no crypto universe snapshot exists"):
        universe_mod.build_point_in_time_crypto_perpetual(
            "2020-01-01", "2020-01-05", as_of_date="2020-01-05", conn=conn
        )


def test_build_point_in_time_crypto_perpetual_builds_universe_from_real_snapshots(tmp_path, monkeypatch):
    from quantbench.data import universe as universe_mod
    from quantbench.data.warehouse import get_connection, record_crypto_universe_snapshot

    conn = get_connection(tmp_path / "wh.duckdb")

    def _fake_ranking(quote="USDT", limit=30):
        return [{"symbol": "BTC/USDT", "quote_volume_24h": 2.0}, {"symbol": "ETH/USDT", "quote_volume_24h": 1.0}]

    monkeypatch.setattr("quantbench.data.providers.ccxt_perpetual.fetch_top_symbols_by_volume", _fake_ranking)
    record_crypto_universe_snapshot(conn, "2026-01-01")
    record_crypto_universe_snapshot(conn, "2026-01-02")

    result = universe_mod.build_point_in_time_crypto_perpetual(
        "2026-01-01", "2026-01-02", as_of_date="2026-01-02", conn=conn
    )

    assert result.point_in_time is True
    assert result.asset_class == "crypto"
    assert set(result.symbols) == {"BTC/USDT", "ETH/USDT"}
    assert result.membership_intervals["BTC/USDT"] == [["2026-01-01", "2026-01-02"]]
    assert "accumulated daily crypto universe snapshots" in result.survivorship_bias_note


def test_build_universe_router_dispatches_crypto_point_in_time(tmp_path, monkeypatch):
    from quantbench.data.universe import build_universe
    from quantbench.data.warehouse import get_connection, record_crypto_universe_snapshot

    conn = get_connection(tmp_path / "wh.duckdb")
    monkeypatch.setattr(
        "quantbench.data.providers.ccxt_perpetual.fetch_top_symbols_by_volume",
        lambda quote="USDT", limit=30: [{"symbol": "BTC/USDT", "quote_volume_24h": 1.0}],
    )
    record_crypto_universe_snapshot(conn, "2026-01-01")

    result = build_universe(
        "usdtperpetual", "2026-01-01", point_in_time=True, start="2026-01-01", end="2026-01-01", conn=conn
    )
    assert result.point_in_time is True
    assert result.symbols == ["BTC/USDT"]


def test_build_universe_router_requires_start_end_for_crypto_pit():
    from quantbench.data.universe import build_universe

    with pytest.raises(ValueError, match="requires start and end"):
        build_universe("usdtperpetual", "2026-01-01", point_in_time=True)
