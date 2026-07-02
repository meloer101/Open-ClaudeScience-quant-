import pandas as pd
import pytest


def test_equity_symbol_uses_yfinance_provider_and_persists_metadata(tmp_path, monkeypatch):
    from quantbench.data import exchange
    from quantbench.data.providers import yfinance_equity

    monkeypatch.setattr("quantbench.data.cache.DATA_CACHE_DIR", tmp_path)

    def fake_yfinance(symbol: str, timeframe: str, start: str, end: str) -> pd.DataFrame:
        assert symbol == "AAPL"
        assert timeframe == "1d"
        return pd.DataFrame(
            {
                "timestamp": pd.date_range("2024-01-01", periods=3, freq="1D", tz="UTC"),
                "open": [100.0, 101.0, 102.0],
                "high": [101.0, 102.0, 103.0],
                "low": [99.0, 100.0, 101.0],
                "close": [100.5, 101.5, 102.5],
                "volume": [1000, 1100, 1200],
            }
        )

    monkeypatch.setattr(yfinance_equity, "download_ohlcv", fake_yfinance)

    path, df, meta = exchange.fetch_ohlcv("AAPL", "1d", "2024-01-01", "2024-01-04")

    assert path.name.startswith("yfinance_equity_AAPL_1d_")
    assert len(df) == 3
    assert meta["provider"] == "yfinance_equity"
    assert meta["source"] == "yfinance"
    assert meta["cache_hit"] is False

    _, _, cached_meta = exchange.fetch_ohlcv("AAPL", "1d", "2024-01-01", "2024-01-04")
    assert cached_meta["cache_hit"] is True
    assert cached_meta["provider"] == "yfinance_equity"
    assert cached_meta["source"] == "yfinance"


def test_crypto_pair_uses_ccxt_provider_cache_namespace(tmp_path, monkeypatch):
    from quantbench.data import exchange
    from quantbench.data.providers import ccxt_perpetual

    monkeypatch.setattr("quantbench.data.cache.DATA_CACHE_DIR", tmp_path)

    def fake_ccxt(symbol: str, timeframe: str, start: str, end: str) -> pd.DataFrame:
        assert symbol == "BTC/USDT"
        return pd.DataFrame(
            {
                "timestamp": pd.date_range("2024-01-01", periods=2, freq="4h", tz="UTC"),
                "open": [100.0, 101.0],
                "high": [102.0, 103.0],
                "low": [99.0, 100.0],
                "close": [101.0, 102.0],
                "volume": [10.0, 11.0],
            }
        )

    monkeypatch.setattr(ccxt_perpetual, "download_ohlcv", fake_ccxt)

    path, _, meta = exchange.fetch_ohlcv("BTC/USDT", "4h", "2024-01-01", "2024-01-02")

    # Provider name/cache namespace is derived from ccxt_perpetual.name rather
    # than hardcoded here, so this test doesn't need editing again the next
    # time the underlying exchange is swapped (see CCXT_EXCHANGE_ID).
    assert path.name.startswith(f"{ccxt_perpetual.name}_BTC_USDT_4h_")
    assert meta["provider"] == ccxt_perpetual.name
    assert meta["source"] == f"{ccxt_perpetual.name}_swap"


@pytest.mark.parametrize(
    ("markets", "requested_symbol", "expected_resolved_symbol"),
    [
        # Binance-style exchange: the bare symbol already IS the perpetual
        # swap market - must be left unchanged.
        (
            {"BTC/USDT": {"swap": True}},
            "BTC/USDT",
            "BTC/USDT",
        ),
        # OKX-style exchange: the bare symbol is the SPOT market, and the
        # perpetual swap is a separate ":USDT"-suffixed market. This is the
        # exact silent-wrong-data bug this test guards against: fetching
        # "BTC/USDT" here must resolve to "BTC/USDT:USDT", not quietly return
        # spot data while the rest of the system assumes perpetual-swap
        # economics.
        (
            {"BTC/USDT": {"swap": False}, "BTC/USDT:USDT": {"swap": True}},
            "BTC/USDT",
            "BTC/USDT:USDT",
        ),
        # Already-qualified symbols are passed through untouched regardless
        # of what's in the market map.
        (
            {"BTC/USDT:USDT": {"swap": True}},
            "BTC/USDT:USDT",
            "BTC/USDT:USDT",
        ),
    ],
)
def test_resolve_swap_symbol_prefers_real_swap_market_over_bare_spot_symbol(
    markets, requested_symbol, expected_resolved_symbol
):
    from quantbench.data.providers.ccxt_perpetual import _resolve_swap_symbol

    class FakeExchange:
        def load_markets(self):
            return markets

    assert _resolve_swap_symbol(FakeExchange(), requested_symbol) == expected_resolved_symbol


def test_download_ohlcv_fetches_the_resolved_swap_symbol_not_the_bare_one(monkeypatch):
    """End-to-end (within the provider module): a bare "ETH/USDT" request
    against an OKX-shaped market map must reach ccxt's fetch_ohlcv with the
    resolved "ETH/USDT:USDT" swap symbol, not the bare spot symbol."""
    from quantbench.data.providers import ccxt_perpetual

    requested_symbols = []

    class FakeExchange:
        def load_markets(self):
            return {"ETH/USDT": {"swap": False}, "ETH/USDT:USDT": {"swap": True}}

        def parse8601(self, value):
            return pd.Timestamp(value).value // 1_000_000

        def fetch_ohlcv(self, symbol, timeframe, since, limit):
            requested_symbols.append(symbol)
            return []

    monkeypatch.setattr(ccxt_perpetual, "_build_exchange", lambda: FakeExchange())

    ccxt_perpetual.download_ohlcv("ETH/USDT", "4h", "2024-01-01", "2024-01-02")

    assert requested_symbols == ["ETH/USDT:USDT"]
