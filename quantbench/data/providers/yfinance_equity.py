import pandas as pd

from quantbench.data.providers.base import Adjustment, ProviderResult


name = "yfinance_equity"

_INTERVALS = {
    "1d": "1d",
    "1wk": "1wk",
    "1mo": "1mo",
    "1h": "1h",
    "60m": "60m",
    "30m": "30m",
    "15m": "15m",
    "5m": "5m",
    "1m": "1m",
}


def fetch_ohlcv(symbol: str, timeframe: str, start: str, end: str) -> ProviderResult:
    return ProviderResult(
        df=download_ohlcv(symbol, timeframe, start, end),
        source="yfinance",
        adjustment=Adjustment(method="raw", dividend_reinvested=False),
    )


def download_ohlcv(symbol: str, timeframe: str, start: str, end: str) -> pd.DataFrame:
    import yfinance as yf  # type: ignore

    interval = _INTERVALS.get(timeframe)
    if not interval:
        raise ValueError(f"Unsupported yfinance timeframe: {timeframe}")

    raw = yf.download(
        symbol,
        start=start,
        end=end,
        interval=interval,
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if raw.empty:
        raise ValueError(f"yfinance returned no rows for {symbol} {timeframe} {start}~{end}")

    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    renamed = raw.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    out = renamed.reset_index().rename(columns={"Date": "timestamp", "Datetime": "timestamp"})
    return out[["timestamp", "open", "high", "low", "close", "volume"]]
