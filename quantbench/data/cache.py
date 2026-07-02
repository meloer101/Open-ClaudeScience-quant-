import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

from quantbench.config import DATA_CACHE_DIR


COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def cache_path_for(
    symbol: str,
    timeframe: str,
    start: str,
    end: str,
    cache_dir: Path | None = None,
    # Never actually relied on: every real caller (exchange.fetch_ohlcv) passes
    # an explicit provider name. Left generic rather than naming one exchange,
    # so this default doesn't quietly go stale the next time the crypto
    # provider's underlying exchange changes (see ccxt_perpetual.py).
    provider: str = "unknown",
) -> Path:
    cache_dir = Path(cache_dir or DATA_CACHE_DIR)
    key = f"{provider}_{symbol}_{timeframe}_{start}_{end}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    safe_symbol = symbol.replace("/", "_").replace(":", "_")
    return cache_dir / f"{provider}_{safe_symbol}_{timeframe}_{digest}.parquet"


def meta_path_for(cache_path: Path) -> Path:
    return cache_path.with_suffix(".meta.json")


def write_cache_meta(cache_path: Path, meta: dict) -> None:
    meta_path_for(cache_path).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def read_cache_meta(cache_path: Path) -> dict:
    path = meta_path_for(cache_path)
    if not path.exists():
        # Cached before provenance tracking existed - can't vouch for it, so treat
        # it as untrusted rather than silently assuming it's real market data.
        return {"source": "unknown_legacy_cache", "fallback_reason": None}
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    normalized = df.loc[:, COLUMNS].copy()
    normalized["timestamp"] = pd.to_datetime(normalized["timestamp"], utc=True)
    return normalized.sort_values("timestamp").reset_index(drop=True)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@contextmanager
def suppress_native_stderr():
    stderr_fd = 2
    saved_fd = os.dup(stderr_fd)
    try:
        with open(os.devnull, "w") as devnull:
            os.dup2(devnull.fileno(), stderr_fd)
            yield
    finally:
        os.dup2(saved_fd, stderr_fd)
        os.close(saved_fd)


def read_parquet_quiet(path: Path) -> pd.DataFrame:
    with suppress_native_stderr():
        return pd.read_parquet(path)


def write_parquet_quiet(df: pd.DataFrame, path: Path) -> None:
    with suppress_native_stderr():
        df.to_parquet(path, index=False)
