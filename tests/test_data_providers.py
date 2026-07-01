import pandas as pd


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
    from quantbench.data.providers import ccxt_binance

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

    monkeypatch.setattr(ccxt_binance, "download_ohlcv", fake_ccxt)

    path, _, meta = exchange.fetch_ohlcv("BTC/USDT", "4h", "2024-01-01", "2024-01-02")

    assert path.name.startswith("ccxt_binance_BTC_USDT_4h_")
    assert meta["provider"] == "ccxt_binance"
    assert meta["source"] == "ccxt_binance_swap"
