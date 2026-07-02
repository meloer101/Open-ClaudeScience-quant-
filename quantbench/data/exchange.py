from pathlib import Path

import numpy as np
import pandas as pd

from quantbench.data.cache import (
    cache_path_for,
    normalize_ohlcv,
    read_cache_meta,
    read_parquet_quiet,
    suppress_native_stderr,
    write_cache_meta,
    write_parquet_quiet,
)
from quantbench.data.providers import ccxt_perpetual, yfinance_equity

SYNTHETIC_FALLBACK_SOURCE = "deterministic_synthetic_fallback"


def fetch_ohlcv(symbol: str, timeframe: str, start: str, end: str) -> tuple[Path, pd.DataFrame, dict]:
    provider = select_provider(symbol)
    cache_path = cache_path_for(symbol, timeframe, start, end, provider=provider.name)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.exists():
        df = read_parquet_quiet(cache_path)
        cached_meta = read_cache_meta(cache_path)
        meta = {"cache_hit": True, "path": str(cache_path), "rows": len(df), "provider": provider.name, **cached_meta}
        return cache_path, normalize_ohlcv(df), meta

    try:
        with suppress_native_stderr():
            result = provider.fetch_ohlcv(symbol, timeframe, start, end)
        df = result.df
        source = result.source
        fallback_error = None
    except Exception as exc:
        df = _synthetic_ohlcv(start, end, timeframe)
        source = SYNTHETIC_FALLBACK_SOURCE
        fallback_error = f"{type(exc).__name__}: {exc}"

    df = normalize_ohlcv(df)
    write_parquet_quiet(df, cache_path)
    meta = {
        "cache_hit": False,
        "path": str(cache_path),
        "rows": len(df),
        "provider": provider.name,
        "source": source,
        "fallback_reason": fallback_error,
    }
    write_cache_meta(cache_path, {"provider": provider.name, "source": source, "fallback_reason": fallback_error})
    return cache_path, df, meta


def select_provider(symbol: str):
    if "/" in symbol or ":" in symbol:
        return ccxt_perpetual
    return yfinance_equity


def _synthetic_ohlcv(start: str, end: str, timeframe: str) -> pd.DataFrame:
    freq = timeframe.lower()
    if freq.endswith("h"):
        pandas_freq = f"{int(freq[:-1])}h"
    elif freq.endswith("d"):
        pandas_freq = f"{int(freq[:-1])}D"
    elif freq.endswith("m"):
        pandas_freq = f"{int(freq[:-1])}min"
    else:
        pandas_freq = "4h"
    timestamps = pd.date_range(start, end, freq=pandas_freq, tz="UTC", inclusive="left")
    if len(timestamps) < 50:
        timestamps = pd.date_range(start, periods=180, freq=pandas_freq, tz="UTC")

    x = np.arange(len(timestamps))
    drift = 0.00025 * x
    cycle = np.sin(x / 17.0) * 0.08 + np.sin(x / 53.0) * 0.13
    shock = np.cos(x / 7.0) * 0.015
    close = 20_000 * np.exp(drift + cycle + shock)
    open_ = close * (1 + np.sin(x / 11.0) * 0.002)
    high = np.maximum(open_, close) * 1.006
    low = np.minimum(open_, close) * 0.994
    volume = 1000 + (np.sin(x / 9.0) + 1) * 400 + x * 0.3
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )
