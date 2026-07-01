import pandas as pd

from quantbench.data.providers.base import ProviderResult


name = "ccxt_binance"


def fetch_ohlcv(symbol: str, timeframe: str, start: str, end: str) -> ProviderResult:
    return ProviderResult(df=download_ohlcv(symbol, timeframe, start, end), source="ccxt_binance_swap")


def download_ohlcv(symbol: str, timeframe: str, start: str, end: str) -> pd.DataFrame:
    import ccxt  # type: ignore

    exchange = ccxt.binance({"enableRateLimit": True, "options": {"defaultType": "swap"}})
    since = exchange.parse8601(f"{start}T00:00:00Z")
    end_ms = exchange.parse8601(f"{end}T00:00:00Z")
    rows = []
    while since < end_ms:
        batch = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since, limit=1000)
        if not batch:
            break
        rows.extend(batch)
        next_since = batch[-1][0] + 1
        if next_since <= since:
            break
        since = next_since
        if batch[-1][0] >= end_ms:
            break

    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df[df["timestamp"] <= pd.Timestamp(end, tz="UTC")]
