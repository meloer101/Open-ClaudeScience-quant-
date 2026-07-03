import os

import pandas as pd

from quantbench.data.providers.base import Adjustment, ProviderResult


name = "polygon_equity"


SCHEMA_MAPPING = {
    "t": "timestamp",
    "o": "open",
    "h": "high",
    "l": "low",
    "c": "close",
    "v": "volume",
}


def fetch_ohlcv(symbol: str, timeframe: str, start: str, end: str) -> ProviderResult:
    api_key = os.environ.get("POLYGON_API_KEY")
    if not api_key:
        raise RuntimeError("POLYGON_API_KEY is not configured; polygon_equity is a formal provider slot only")
    raise NotImplementedError(
        "polygon_equity schema slot is defined, but live Polygon fetch is intentionally not enabled in Phase 11"
    )


def normalize_polygon_aggs(rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    out = frame.rename(columns=SCHEMA_MAPPING)
    out["timestamp"] = pd.to_datetime(out["timestamp"], unit="ms", utc=True)
    return out[["timestamp", "open", "high", "low", "close", "volume"]]


def provider_result_from_rows(rows: list[dict]) -> ProviderResult:
    return ProviderResult(
        df=normalize_polygon_aggs(rows),
        source="polygon_aggs",
        adjustment=Adjustment(method="split_dividend", dividend_reinvested=False),
    )
