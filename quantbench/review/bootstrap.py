from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

from quantbench.engine.metrics import annualized_return, annualized_sharpe, periods_per_year_from_timestamps


MetricName = Literal["sharpe", "annual_return"]


def block_bootstrap_ci(
    returns: pd.Series,
    *,
    metric: MetricName = "sharpe",
    n_boot: int = 1000,
    block_size: int | None = None,
    alpha: float = 0.05,
) -> tuple[float, float, float]:
    clean = pd.Series(returns, dtype="float64").replace([np.inf, -np.inf], np.nan).fillna(0.0)
    if clean.empty:
        return 0.0, 0.0, 0.0
    block_size = int(block_size or max(1, round(np.sqrt(len(clean)))))
    ppy = periods_per_year_from_timestamps(clean.index)
    point = _metric(clean, metric, ppy)
    if len(clean) < 2 or n_boot <= 0:
        rounded = round(float(point), 6)
        return rounded, rounded, rounded
    rng = np.random.default_rng(42)
    values = []
    array = clean.to_numpy(dtype=float)
    for _ in range(int(n_boot)):
        sample = _sample_blocks(array, block_size, rng)
        values.append(_metric(pd.Series(sample), metric, ppy))
    lower, upper = np.quantile(values, [alpha / 2.0, 1.0 - alpha / 2.0])
    return round(float(point), 6), round(float(lower), 6), round(float(upper), 6)


def metrics_ci(returns: pd.Series, *, n_boot: int = 300) -> dict[str, dict[str, float]]:
    intervals: dict[str, dict[str, float]] = {}
    for metric in ("sharpe", "annual_return"):
        point, lower, upper = block_bootstrap_ci(returns, metric=metric, n_boot=n_boot)
        intervals[metric] = {"point": point, "lower": lower, "upper": upper}
    return intervals


def _sample_blocks(array: np.ndarray, block_size: int, rng: np.random.Generator) -> np.ndarray:
    starts = rng.integers(0, len(array), size=int(np.ceil(len(array) / block_size)))
    chunks = []
    for start in starts:
        positions = (np.arange(start, start + block_size) % len(array)).astype(int)
        chunks.append(array[positions])
    return np.concatenate(chunks)[: len(array)]


def _metric(returns: pd.Series, metric: str, periods_per_year: float) -> float:
    if metric == "annual_return":
        return annualized_return(returns, periods_per_year)
    if metric == "sharpe":
        return annualized_sharpe(returns, periods_per_year)
    raise ValueError(f"unsupported bootstrap metric: {metric}")
