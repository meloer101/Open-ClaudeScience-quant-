import os

import pandas as pd

from quantbench.data.providers.base import ProviderResult


# Which ccxt exchange serves crypto perpetual swap data. Binance's site/API is
# blocked from some regions (e.g. mainland China without a proxy); swapping
# this one constant - or setting the QUANTBENCH_CCXT_EXCHANGE env var - is the
# whole fix. No other module needs exchange-specific knowledge: bare
# "BTC/USDT"-style symbols are normalized to whatever the active exchange's
# real perpetual swap market symbol is (see _resolve_swap_symbol below), so
# prompts.py/coordinator.py/tests can keep using the Binance-style convention
# regardless of which exchange is actually configured.
CCXT_EXCHANGE_ID = os.environ.get("QUANTBENCH_CCXT_EXCHANGE", "okx")

name = f"ccxt_{CCXT_EXCHANGE_ID}"


def _build_exchange():
    import ccxt  # type: ignore

    exchange_class = getattr(ccxt, CCXT_EXCHANGE_ID)
    return exchange_class({"enableRateLimit": True, "options": {"defaultType": "swap"}})


def _resolve_swap_symbol(exchange, symbol: str) -> str:
    """Bare "BTC/USDT"-style symbols mean different markets on different
    exchanges: on Binance it already IS the USDT-margined perpetual swap
    market, but on OKX (and several other exchanges) the bare symbol resolves
    to the SPOT market instead - the actual perpetual swap is a separate
    market with a ":USDT" suffix (e.g. "BTC/USDT:USDT"). Silently fetching
    spot data while the rest of the system assumes perpetual-swap economics
    would be exactly the kind of result that looks fine but is quietly wrong
    that this project exists to prevent, so every bare crypto symbol is
    resolved to its exchange's real swap market before any OHLCV/ticker call
    - never left to whichever market ccxt's default symbol lookup happens to
    pick."""
    if ":" in symbol:
        return symbol
    markets = exchange.load_markets()
    market = markets.get(symbol)
    if market is not None and market.get("swap") is True:
        return symbol
    quote = symbol.split("/")[-1]
    swap_symbol = f"{symbol}:{quote}"
    if swap_symbol in markets:
        return swap_symbol
    return symbol


def fetch_ohlcv(symbol: str, timeframe: str, start: str, end: str) -> ProviderResult:
    return ProviderResult(df=download_ohlcv(symbol, timeframe, start, end), source=f"{name}_swap")


def fetch_top_symbols_by_volume(quote: str = "USDT", limit: int = 30) -> list[dict]:
    """Current top perpetual swap markets by 24h quote volume, active markets only."""
    if limit < 1:
        raise ValueError("limit must be at least 1")

    exchange = _build_exchange()
    markets = exchange.load_markets()
    tickers = exchange.fetch_tickers()

    rows: list[dict] = []
    for symbol, market in markets.items():
        if market.get("quote") != quote:
            continue
        if market.get("swap") is not True:
            continue
        if market.get("active") is not True:
            continue

        ticker = tickers.get(symbol) or tickers.get(market.get("symbol")) or tickers.get(market.get("id"))
        quote_volume = _ticker_quote_volume(ticker or {})
        if quote_volume is None:
            continue
        rows.append({"symbol": str(market.get("symbol") or symbol), "quote_volume_24h": quote_volume})

    return sorted(rows, key=lambda row: row["quote_volume_24h"], reverse=True)[:limit]


# ccxt's "unified" ticker field isn't actually populated the same way on
# every exchange for derivatives: Binance's swap tickers set quoteVolume
# directly, but OKX's swap tickers leave the unified quoteVolume field None
# and only report 24h quote-currency volume under this exchange-specific raw
# key in `info`. Found by testing against a real OKX universe build - this
# silently returned zero symbols (every quote_volume came back None) before
# this fallback was added, not an error, so it would have been easy to miss.
_RAW_INFO_QUOTE_VOLUME_KEYS = ("volCcy24h",)


def _ticker_quote_volume(ticker: dict) -> float | None:
    value = ticker.get("quoteVolume") or ticker.get("quote_volume")
    if value is None:
        info = ticker.get("info") or {}
        value = info.get("quoteVolume") or info.get("quote_volume")
        for key in _RAW_INFO_QUOTE_VOLUME_KEYS:
            if value is not None:
                break
            value = info.get(key)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def download_ohlcv(symbol: str, timeframe: str, start: str, end: str) -> pd.DataFrame:
    exchange = _build_exchange()
    resolved_symbol = _resolve_swap_symbol(exchange, symbol)
    since = exchange.parse8601(f"{start}T00:00:00Z")
    end_ms = exchange.parse8601(f"{end}T00:00:00Z")
    rows = []
    while since < end_ms:
        batch = exchange.fetch_ohlcv(resolved_symbol, timeframe=timeframe, since=since, limit=1000)
        if not batch:
            break
        rows.extend(batch)
        next_since = batch[-1][0] + 1
        if next_since <= since:
            break
        since = next_since
        if batch[-1][0] >= end_ms:
            break

    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df[df["timestamp"] <= pd.Timestamp(end, tz="UTC")]
