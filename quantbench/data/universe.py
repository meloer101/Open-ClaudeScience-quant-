from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from quantbench.data.providers.ccxt_perpetual import fetch_top_symbols_by_volume
from quantbench.data.providers.ccxt_perpetual import name as ccxt_provider_name
from quantbench.data.providers.sp500_constituents import WIKIPEDIA_SP500_URL, fetch_current_constituents
from quantbench.data.providers.sp500_history import build_point_in_time_sp500


SURVIVORSHIP_BIAS_NOTE = (
    "This universe uses the current S&P 500 constituents across the requested "
    "history. It is not point-in-time and therefore has survivorship bias: "
    "companies removed from the index before the as-of date are absent from "
    "the historical backtest sample."
)


LIMITED_SAMPLE_NOTE_TEMPLATE = (
    "This universe was truncated to a {limit}-symbol sample of the full S&P 500 "
    "(alphabetically first {limit} tickers), for a quick/cheap test run. It is "
    "NOT representative of the full index and results must not be interpreted "
    "as an S&P 500-wide finding."
)


CRYPTO_UNIVERSE_NOTE = (
    "This universe uses the current top-N USDT perpetual swap markets by 24h "
    "trading volume (queried at run time, not as of `as_of_date`), applied "
    "across the requested historical window. Perpetuals delisted before "
    "`as_of_date` are absent, and the volume ranking may not reflect the "
    "historical ranking at `as_of_date` - this is not a point-in-time universe."
)


PIT_SP500_NOTE = (
    "This universe uses point-in-time S&P 500 membership intervals over the requested "
    "backtest window, so the universe definition itself is not survivorship-biased. "
    "Data coverage for removed or delisted members is still audited separately."
)


@dataclass(frozen=True)
class UniverseDefinition:
    name: str
    as_of_date: str
    symbols: list[str]
    point_in_time: bool
    survivorship_bias_note: str
    source: str
    sample_limit: int | None = None
    asset_class: str = "equity"
    membership_intervals: dict[str, list[list[str]]] | None = None
    covers_delisted: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    def save_yaml(self, path: Path) -> Path:
        path.write_text(yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True), encoding="utf-8")
        return path


def build_sp500_universe(
    as_of_date: str,
    point_in_time: bool = False,
    limit: int | None = None,
    start: str | None = None,
    end: str | None = None,
) -> UniverseDefinition:
    if point_in_time:
        if not start or not end:
            raise ValueError("point-in-time S&P 500 universe requires start and end")
        symbols, intervals = build_point_in_time_sp500(start, end)
        normalized_intervals = _serializable_intervals(intervals)
        note = PIT_SP500_NOTE
        if limit is not None:
            if limit < 1:
                raise ValueError("limit must be at least 1")
            symbols = symbols[:limit]
            normalized_intervals = {symbol: normalized_intervals[symbol] for symbol in symbols}
            note = f"{PIT_SP500_NOTE} {LIMITED_SAMPLE_NOTE_TEMPLATE.format(limit=limit)}"
        return UniverseDefinition(
            name="sp500",
            as_of_date=as_of_date,
            symbols=symbols,
            point_in_time=True,
            survivorship_bias_note=note,
            source=WIKIPEDIA_SP500_URL,
            sample_limit=limit,
            asset_class="equity",
            membership_intervals=normalized_intervals,
            covers_delisted=False,
        )

    constituents = fetch_current_constituents()
    symbols = sorted(constituents["Symbol"].dropna().astype(str).unique().tolist())
    if len(symbols) < 400:
        raise ValueError(f"S&P 500 constituent parse returned too few symbols: {len(symbols)}")

    note = SURVIVORSHIP_BIAS_NOTE
    if limit is not None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        symbols = symbols[:limit]
        note = f"{SURVIVORSHIP_BIAS_NOTE} {LIMITED_SAMPLE_NOTE_TEMPLATE.format(limit=limit)}"

    return UniverseDefinition(
        name="sp500",
        as_of_date=as_of_date,
        symbols=symbols,
        point_in_time=False,
        survivorship_bias_note=note,
        source=WIKIPEDIA_SP500_URL,
        sample_limit=limit,
        asset_class="equity",
    )


def build_crypto_perpetual_universe(as_of_date: str, limit: int = 30) -> UniverseDefinition:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    top = fetch_top_symbols_by_volume(quote="USDT", limit=limit)
    if not top:
        raise ValueError(f"No active USDT perpetual swap markets returned by {ccxt_provider_name}")

    return UniverseDefinition(
        name="top_usdt_perpetual",
        as_of_date=as_of_date,
        symbols=[str(row["symbol"]) for row in top],
        point_in_time=False,
        survivorship_bias_note=CRYPTO_UNIVERSE_NOTE,
        source=f"{ccxt_provider_name}_tickers",
        sample_limit=limit,
        asset_class="crypto",
    )


def build_universe(
    name: str,
    as_of_date: str,
    point_in_time: bool = False,
    limit: int | None = None,
    start: str | None = None,
    end: str | None = None,
) -> UniverseDefinition:
    normalized = name.lower().replace("-", "").replace("_", "")
    if normalized in {"sp500", "s&p500", "sandp500"}:
        return build_sp500_universe(
            as_of_date=as_of_date,
            point_in_time=point_in_time,
            limit=limit,
            start=start,
            end=end,
        )
    top_n_match = re.fullmatch(r"top(\d+)usdtperpetual", normalized)
    if normalized in {"topusdtperpetual", "cryptoperpetual", "usdtperpetual"} or top_n_match:
        if point_in_time:
            raise NotImplementedError("Point-in-time crypto perpetual membership is not implemented in Phase 5 v1")
        parsed_limit = int(top_n_match.group(1)) if top_n_match else 30
        return build_crypto_perpetual_universe(as_of_date=as_of_date, limit=limit or parsed_limit)
    raise ValueError(f"Unsupported universe: {name}")


def _serializable_intervals(
    intervals: dict[str, list[tuple[str, str]]] | dict[str, list[list[str]]],
) -> dict[str, list[list[str]]]:
    return {
        str(symbol): [[str(start), str(end)] for start, end in spans]
        for symbol, spans in intervals.items()
    }
