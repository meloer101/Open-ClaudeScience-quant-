from dataclasses import asdict, dataclass
from typing import Protocol

import pandas as pd


@dataclass(frozen=True)
class Adjustment:
    method: str
    dividend_reinvested: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ProviderResult:
    df: pd.DataFrame
    source: str
    fallback_reason: str | None = None
    adjustment: Adjustment | None = None
    # GAP 1.2: does this provider's fetch_ohlcv reliably return delisted-symbol
    # history? A capability the provider itself declares, rather than a universe
    # metadata field hardcoded to False everywhere it's built - see
    # quantbench.data.universe.apply_covers_delisted for how this propagates.
    covers_delisted: bool = False


class MarketDataProvider(Protocol):
    name: str

    def fetch_ohlcv(self, symbol: str, timeframe: str, start: str, end: str) -> ProviderResult:
        ...
