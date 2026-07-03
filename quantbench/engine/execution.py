from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd


@dataclass(frozen=True)
class ExecutionConfig:
    signal_time: str = "close_t"
    fill_price: str = "close_t"

    def __post_init__(self) -> None:
        allowed = {"close_t", "open_t+1", "close_t+1"}
        if self.fill_price not in allowed:
            raise ValueError(f"fill_price must be one of {sorted(allowed)}, got {self.fill_price!r}")

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def forward_returns_for_execution(price_df: pd.DataFrame, execution: ExecutionConfig) -> pd.Series:
    if execution.fill_price == "close_t":
        return price_df["close"].pct_change().shift(-1)
    if execution.fill_price == "close_t+1":
        # Filled at the next close: the signal at t earns close_{t+2}/close_{t+1}-1.
        return price_df["close"].pct_change().shift(-2)
    if "open" not in price_df.columns:
        return price_df["close"].pct_change().shift(-1)
    next_open = price_df["open"].shift(-1)
    next_close = price_df["close"].shift(-1)
    return next_close / next_open - 1
