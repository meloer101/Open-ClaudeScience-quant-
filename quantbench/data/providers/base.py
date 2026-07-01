from dataclasses import dataclass
from typing import Protocol

import pandas as pd


@dataclass(frozen=True)
class ProviderResult:
    df: pd.DataFrame
    source: str
    fallback_reason: str | None = None


class MarketDataProvider(Protocol):
    name: str

    def fetch_ohlcv(self, symbol: str, timeframe: str, start: str, end: str) -> ProviderResult:
        ...
