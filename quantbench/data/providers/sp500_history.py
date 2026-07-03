from __future__ import annotations

from io import StringIO

import pandas as pd
import requests

from quantbench.data.providers.sp500_constituents import (
    WIKIPEDIA_SP500_URL,
    fetch_current_constituents,
)


def _normalize_ticker(value: object) -> str | None:
    """Wikipedia uses dots for share classes (BRK.B); yfinance expects dashes
    (BRK-B). Mirror fetch_current_constituents so historical and current
    tickers line up. Empty / NaN cells become None."""
    if value is None:
        return None
    text = str(value).replace(".", "-").strip()
    if not text or text.lower() == "nan":
        return None
    return text


def fetch_constituent_changes() -> pd.DataFrame:
    """Parse the 'Selected changes to the list of S&P 500 components' table
    from the same Wikipedia page fetch_current_constituents reads.

    Returns a frame with columns [effective_date, added, removed] sorted by
    effective_date ascending. `added`/`removed` are normalized tickers or None.
    Rows whose date does not parse are dropped (footnote artifacts).
    """
    response = requests.get(
        WIKIPEDIA_SP500_URL, timeout=30, headers={"User-Agent": "quantbench/0.1"}
    )
    response.raise_for_status()
    tables = pd.read_html(StringIO(response.text))
    if len(tables) < 2:
        raise ValueError("Wikipedia S&P 500 page did not return a changes table")

    changes = tables[1].copy()
    # The changes table has a two-level header: ('Effective Date', ...),
    # ('Added', 'Ticker'), ('Removed', 'Ticker'), ('Reason', ...). Flatten it
    # positionally rather than by label so a future header-text tweak on
    # Wikipedia doesn't silently drop columns.
    changes.columns = [
        "effective_date",
        "added_ticker",
        "added_security",
        "removed_ticker",
        "removed_security",
        "reason",
    ][: changes.shape[1]]

    return _normalize_changes(changes)


def _normalize_changes(changes: pd.DataFrame) -> pd.DataFrame:
    effective_date = pd.to_datetime(changes["effective_date"], errors="coerce", utc=True)
    frame = pd.DataFrame(
        {
            "effective_date": effective_date,
            "added": changes["added_ticker"].map(_normalize_ticker),
            "removed": changes["removed_ticker"].map(_normalize_ticker),
        }
    )
    frame = frame.dropna(subset=["effective_date"])
    frame = frame[~(frame["added"].isna() & frame["removed"].isna())]
    return frame.sort_values("effective_date").reset_index(drop=True)


def reconstruct_membership(
    as_of_date: str, current_symbols: set[str], changes: pd.DataFrame
) -> set[str]:
    """The true S&P 500 membership set as of `as_of_date`.

    Starts from today's members and reverses every change effective strictly
    after `as_of_date`: an `added` ticker was not yet a member before its
    effective date (remove it), a `removed` ticker still was (add it back).
    """
    as_of = pd.to_datetime(as_of_date, utc=True)
    members = set(current_symbols)
    future = changes[changes["effective_date"] > as_of]
    # Reverse most-recent-first so intermediate states stay consistent when a
    # ticker is added and later removed within the reversed span.
    for row in future.sort_values("effective_date", ascending=False).itertuples():
        if isinstance(row.added, str) and row.added in members:
            members.discard(row.added)
        if isinstance(row.removed, str):
            members.add(row.removed)
    return members


def earliest_supported_date(changes: pd.DataFrame) -> pd.Timestamp | None:
    """The oldest effective date the changes table covers. Reconstruction for
    dates at/after this is trustworthy; before it, the log is incomplete and
    callers should refuse rather than silently return a survivorship-biased
    snapshot."""
    if changes.empty:
        return None
    return changes["effective_date"].min()


def membership_intervals(
    start: str,
    end: str,
    current_symbols: set[str],
    changes: pd.DataFrame,
) -> dict[str, list[tuple[str, str]]]:
    """Per-symbol membership intervals clipped to [start, end].

    Returns {ticker: [(interval_start_iso, interval_end_iso), ...]} for every
    ticker that was a member at any point in the window - the union of these
    keys is exactly the set of symbols worth fetching OHLCV for. Interval
    bounds are ISO date strings so the map serializes cleanly into the
    universe YAML/manifest.
    """
    window_start = pd.to_datetime(start, utc=True)
    window_end = pd.to_datetime(end, utc=True)
    if window_end < window_start:
        raise ValueError("end must be on or after start")

    members = reconstruct_membership(start, current_symbols, changes)
    open_since: dict[str, pd.Timestamp] = {symbol: window_start for symbol in members}
    intervals: dict[str, list[tuple[str, str]]] = {}

    in_window = changes[
        (changes["effective_date"] > window_start) & (changes["effective_date"] <= window_end)
    ]
    for row in in_window.itertuples():
        date = row.effective_date
        if isinstance(row.removed, str) and row.removed in open_since:
            intervals.setdefault(row.removed, []).append(
                (open_since.pop(row.removed).date().isoformat(), date.date().isoformat())
            )
        if isinstance(row.added, str) and row.added not in open_since:
            open_since[row.added] = date

    for symbol, opened in open_since.items():
        intervals.setdefault(symbol, []).append(
            (opened.date().isoformat(), window_end.date().isoformat())
        )
    return intervals


def build_point_in_time_sp500(start: str, end: str) -> tuple[list[str], dict[str, list[tuple[str, str]]]]:
    """Fetch live Wikipedia data and return (symbols, membership_intervals) for
    a point-in-time S&P 500 over [start, end]. Raises if the window reaches
    before the changes log's coverage."""
    current = set(
        fetch_current_constituents()["Symbol"].dropna().astype(str).tolist()
    )
    changes = fetch_constituent_changes()
    earliest = earliest_supported_date(changes)
    if earliest is not None and pd.to_datetime(start, utc=True) < earliest:
        raise ValueError(
            f"point-in-time S&P 500 is only reconstructable back to "
            f"{earliest.date().isoformat()}; requested start {start} is earlier and would "
            "reintroduce survivorship bias. Use a later start date or the non-PIT snapshot."
        )
    intervals = membership_intervals(start, end, current, changes)
    symbols = sorted(intervals.keys())
    return symbols, intervals
