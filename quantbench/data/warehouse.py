from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from quantbench.config import DATA_CACHE_DIR
from quantbench.data.cache import file_sha256
from quantbench.data.exchange import fetch_ohlcv
from quantbench.data.providers.ccxt_perpetual import fetch_funding_rate
from quantbench.data.universe import UniverseDefinition


OHLCV_TABLE = "ohlcv"
FUNDING_TABLE = "funding_rates"


def get_connection(db_path: Path | None = None) -> duckdb.DuckDBPyConnection:
    db_path = Path(db_path or DATA_CACHE_DIR / "quantbench.duckdb")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(db_path))
    ensure_schema(conn)
    return conn


def ensure_schema(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {OHLCV_TABLE} (
            symbol VARCHAR NOT NULL,
            timestamp TIMESTAMPTZ NOT NULL,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            volume DOUBLE,
            provider VARCHAR,
            source VARCHAR,
            PRIMARY KEY (symbol, timestamp)
        )
        """
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {FUNDING_TABLE} (
            symbol VARCHAR NOT NULL,
            timestamp TIMESTAMPTZ NOT NULL,
            funding_rate DOUBLE,
            provider VARCHAR,
            source VARCHAR,
            PRIMARY KEY (symbol, timestamp)
        )
        """
    )


def upsert_ohlcv(
    conn: duckdb.DuckDBPyConnection,
    symbol: str,
    df: pd.DataFrame,
    provider: str | None = None,
    source: str | None = None,
) -> int:
    ensure_schema(conn)
    if df.empty:
        return 0

    rows = df[["timestamp", "open", "high", "low", "close", "volume"]].copy()
    rows["timestamp"] = pd.to_datetime(rows["timestamp"], utc=True)
    rows.insert(0, "symbol", symbol)
    rows["provider"] = provider
    rows["source"] = source

    conn.register("_incoming_ohlcv", rows)
    try:
        conn.execute(
            f"""
            INSERT OR REPLACE INTO {OHLCV_TABLE}
            SELECT symbol, timestamp, open, high, low, close, volume, provider, source
            FROM _incoming_ohlcv
            """
        )
    finally:
        conn.unregister("_incoming_ohlcv")
    return len(rows)


def upsert_funding_rates(
    conn: duckdb.DuckDBPyConnection,
    symbol: str,
    df: pd.DataFrame,
    provider: str | None = None,
    source: str | None = None,
) -> int:
    ensure_schema(conn)
    if df.empty:
        return 0
    rows = df[["timestamp", "funding_rate"]].copy()
    rows["timestamp"] = pd.to_datetime(rows["timestamp"], utc=True)
    rows.insert(0, "symbol", symbol)
    rows["provider"] = provider
    rows["source"] = source
    conn.register("_incoming_funding_rates", rows)
    try:
        conn.execute(
            f"""
            INSERT OR REPLACE INTO {FUNDING_TABLE}
            SELECT symbol, timestamp, funding_rate, provider, source
            FROM _incoming_funding_rates
            """
        )
    finally:
        conn.unregister("_incoming_funding_rates")
    return len(rows)


def query_universe_ohlcv(
    conn: duckdb.DuckDBPyConnection,
    symbols: list[str],
    start: str,
    end: str,
) -> pd.DataFrame:
    ensure_schema(conn)
    if not symbols:
        return pd.DataFrame(columns=["symbol", "timestamp", "open", "high", "low", "close", "volume"])

    query = f"""
        SELECT symbol, timestamp, open, high, low, close, volume
        FROM {OHLCV_TABLE}
        WHERE symbol IN (SELECT * FROM UNNEST(?))
          AND timestamp >= ?
          AND timestamp < ?
        ORDER BY timestamp, symbol
    """
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    return conn.execute(query, [symbols, start_ts, end_ts]).fetchdf()


def query_universe_funding_rates(
    conn: duckdb.DuckDBPyConnection,
    symbols: list[str],
    start: str,
    end: str,
) -> pd.DataFrame:
    ensure_schema(conn)
    if not symbols:
        return pd.DataFrame(columns=["symbol", "timestamp", "funding_rate"])
    query = f"""
        SELECT symbol, timestamp, funding_rate
        FROM {FUNDING_TABLE}
        WHERE symbol IN (SELECT * FROM UNNEST(?))
          AND timestamp >= ?
          AND timestamp < ?
        ORDER BY timestamp, symbol
    """
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    return conn.execute(query, [symbols, start_ts, end_ts]).fetchdf()


def fetch_universe_ohlcv(
    universe: UniverseDefinition,
    timeframe: str,
    start: str,
    end: str,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> tuple[pd.DataFrame, dict]:
    own_conn = conn is None
    conn = conn or get_connection()
    cache_hits = 0
    fetched = 0
    failed: dict[str, str] = {}
    sources: dict[str, int] = {}
    data_slices: list[dict] = []

    for symbol in universe.symbols:
        try:
            path, df, meta = fetch_ohlcv(symbol, timeframe, start, end)
            upsert_ohlcv(conn, symbol, df, provider=meta.get("provider"), source=meta.get("source"))
            cache_hits += int(bool(meta.get("cache_hit")))
            fetched += 1
            source = str(meta.get("source", "unknown"))
            sources[source] = sources.get(source, 0) + 1
            data_slices.append(
                {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "start": start,
                    "end": end,
                    "path": str(path),
                    "content_hash": str(meta.get("content_hash") or file_sha256(path)),
                    "rows": int(meta.get("rows") or len(df)),
                    "provider": meta.get("provider"),
                    "source": meta.get("source"),
                    "adjustment": meta.get("adjustment"),
                    "fallback_reason": meta.get("fallback_reason"),
                }
            )
        except Exception as exc:
            failed[symbol] = f"{type(exc).__name__}: {exc}"

    panel = query_universe_ohlcv(conn, universe.symbols, start, end)
    if own_conn:
        conn.close()

    meta = {
        "symbols_requested": len(universe.symbols),
        "symbols_fetched": fetched,
        "cache_hits": cache_hits,
        "failed": failed,
        "sources": sources,
        "data_slices": data_slices,
    }
    if universe.point_in_time and universe.membership_intervals:
        meta["coverage_report"] = universe_coverage_report(universe, panel, start, end, timeframe=timeframe)
    return panel, meta


def fetch_universe_funding_rates(
    universe: UniverseDefinition,
    start: str,
    end: str,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> tuple[pd.DataFrame, dict]:
    own_conn = conn is None
    conn = conn or get_connection()
    fetched = 0
    failed: dict[str, str] = {}
    sources: dict[str, int] = {}
    if universe.asset_class != "crypto":
        if own_conn:
            conn.close()
        return pd.DataFrame(columns=["symbol", "timestamp", "funding_rate"]), {
            "symbols_requested": 0,
            "symbols_fetched": 0,
            "failed": {},
            "sources": {},
        }
    for symbol in universe.symbols:
        try:
            result = fetch_funding_rate(symbol, start, end)
            upsert_funding_rates(conn, symbol, result.df, provider="ccxt", source=result.source)
            fetched += 1
            sources[result.source] = sources.get(result.source, 0) + 1
        except Exception as exc:
            failed[symbol] = f"{type(exc).__name__}: {exc}"
    panel = query_universe_funding_rates(conn, universe.symbols, start, end)
    if own_conn:
        conn.close()
    return panel, {
        "symbols_requested": len(universe.symbols),
        "symbols_fetched": fetched,
        "failed": failed,
        "sources": sources,
    }


def universe_coverage_report(
    universe: UniverseDefinition,
    panel: pd.DataFrame,
    start: str,
    end: str,
    timeframe: str,
) -> dict:
    intervals = universe.membership_intervals or {
        symbol: [[start, end]] for symbol in universe.symbols
    }
    observed_by_symbol: dict[str, set[pd.Timestamp]] = {}
    # The trading calendar implied by the data itself: every timestamp on which
    # ANY member actually traded. Expecting bars only on these days (rather than
    # pandas business days) avoids charging exchange holidays - which are never
    # trading days - as "missing", and works for 5-day equity and 7-day crypto
    # calendars without special-casing timeframe/asset_class.
    trading_days: set[pd.Timestamp] = set()
    if not panel.empty and "symbol" in panel and "timestamp" in panel:
        normalized = panel.copy()
        normalized["timestamp"] = pd.to_datetime(normalized["timestamp"], utc=True)
        for symbol, rows in normalized.groupby("symbol"):
            observed = set(rows["timestamp"])
            observed_by_symbol[str(symbol)] = observed
            trading_days |= observed
    trading_calendar = sorted(trading_days)

    per_symbol: dict[str, dict] = {}
    expected_total = 0
    observed_total = 0
    run_start = pd.to_datetime(start, utc=True)
    run_end = pd.to_datetime(end, utc=True)

    for symbol in universe.symbols:
        expected_dates: set[pd.Timestamp] = set()
        for interval_start, interval_end in intervals.get(symbol, []):
            clipped_start = max(pd.to_datetime(interval_start, utc=True), run_start)
            clipped_end = min(pd.to_datetime(interval_end, utc=True), run_end)
            if clipped_end < clipped_start:
                continue
            expected_dates.update(day for day in trading_calendar if clipped_start <= day <= clipped_end)
        observed_dates = observed_by_symbol.get(symbol, set()) & expected_dates
        expected = len(expected_dates)
        observed = len(observed_dates)
        missing = max(expected - observed, 0)
        expected_total += expected
        observed_total += observed
        per_symbol[symbol] = {
            "expected_bars": expected,
            "observed_bars": observed,
            "missing_bars": missing,
            "coverage": round(observed / expected, 6) if expected else None,
        }

    missing_total = max(expected_total - observed_total, 0)
    symbols_missing_entirely = [
        symbol for symbol, stats in per_symbol.items() if stats["expected_bars"] > 0 and stats["observed_bars"] == 0
    ]
    symbols_with_data = [
        symbol for symbol, stats in per_symbol.items() if stats["observed_bars"] > 0
    ]
    return {
        "point_in_time": universe.point_in_time,
        "covers_delisted": universe.covers_delisted,
        "expected_member_bars": expected_total,
        "observed_member_bars": observed_total,
        "missing_member_bars": missing_total,
        "missing_rate": round(missing_total / expected_total, 6) if expected_total else 0.0,
        "symbols_expected": sum(1 for stats in per_symbol.values() if stats["expected_bars"] > 0),
        "symbols_with_data": len(symbols_with_data),
        "symbols_missing_entirely": symbols_missing_entirely,
        "per_symbol": per_symbol,
    }
