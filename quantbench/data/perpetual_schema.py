from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class PerpetualMarketRow:
    timestamp: str
    symbol: str
    close: float
    volume: float
    funding_rate: float | None = None
    open_interest: float | None = None

    def to_row(self) -> dict:
        return asdict(self)


PERPETUAL_OPTIONAL_COLUMNS = ("funding_rate", "open_interest")
