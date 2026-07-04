from __future__ import annotations

import pandas as pd


def reconstruct_crypto_membership_intervals(
    daily_snapshots: dict[str, list[str] | None],
) -> dict[str, list[tuple[str, str]]]:
    """Turns a day-by-day series of crypto universe snapshots (each day's
    top-N symbol list, or None if that day was never snapshotted - see
    quantbench.data.warehouse.query_crypto_universe_snapshot) into per-symbol
    membership intervals.

    Unlike S&P 500's reconstruction (quantbench.data.providers.sp500_history),
    which replays a complete add/remove event log, this works from sparse
    daily samples: a symbol's interval only spans days it was *actually*
    confirmed present in a snapshot. A day with no snapshot at all closes any
    open interval rather than being silently bridged - we genuinely don't know
    whether a symbol stayed in the top-N through an un-snapshotted gap, and
    optimistically assuming continuity would manufacture point-in-time
    correctness the data doesn't support.
    """
    ordered_dates = sorted(daily_snapshots.keys())
    open_since: dict[str, str] = {}
    intervals: dict[str, list[tuple[str, str]]] = {}
    last_seen: dict[str, str] = {}

    def _close_all_open(as_of: str) -> None:
        for symbol, start in list(open_since.items()):
            intervals.setdefault(symbol, []).append((start, last_seen.get(symbol, as_of)))
            open_since.pop(symbol)

    previous_date: str | None = None
    for date in ordered_dates:
        symbols = daily_snapshots.get(date)
        if symbols is None:
            # A gap in snapshot coverage itself - close whatever was open as of
            # the last day we actually had data for, don't bridge across it.
            _close_all_open(previous_date or date)
            previous_date = date
            continue

        present = set(symbols)
        for symbol in present:
            if symbol not in open_since:
                open_since[symbol] = date
            last_seen[symbol] = date
        for symbol in list(open_since.keys()):
            if symbol not in present:
                intervals.setdefault(symbol, []).append((open_since.pop(symbol), last_seen[symbol]))
        previous_date = date

    _close_all_open(previous_date or "")
    return intervals


def earliest_snapshot_date(daily_snapshots: dict[str, list[str] | None]) -> str | None:
    snapshotted = [date for date, symbols in daily_snapshots.items() if symbols is not None]
    return min(snapshotted) if snapshotted else None


def daily_date_range(start: str, end: str) -> list[str]:
    return [str(day.date()) for day in pd.date_range(start, end, freq="1D", tz="UTC")]
