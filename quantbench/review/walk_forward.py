from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from quantbench.engine.metrics import annualized_sharpe, periods_per_year_from_timestamps


@dataclass(frozen=True)
class WalkForwardResult:
    window_test_sharpes: list[float]
    median_test_sharpe: float
    iqr_test_sharpe: float
    positive_window_share: float
    n_windows: int


def run_walk_forward(
    returns: pd.Series,
    *,
    n_windows: int = 4,
    embargo_bars: int = 0,
) -> WalkForwardResult:
    """Roll the OOS window across the already-computed period return series.

    Like `run_cpcv`, this selects periods from a timestamp-indexed return series
    rather than slicing a long panel by row position and recomputing. Row-position
    slicing cuts through a single timestamp's cross-section in a long-format panel;
    selecting periods from the return series sidesteps that entirely.
    """
    clean = pd.Series(returns, dtype="float64").replace([np.inf, -np.inf], np.nan).dropna()
    n = int(len(clean))
    if n_windows < 1 or n < n_windows:
        return WalkForwardResult([], 0.0, 0.0, 0.0, 0)
    periods = periods_per_year_from_timestamps(clean.index)
    values = clean.to_numpy(dtype=float)
    cut_points = np.linspace(0, n, n_windows + 1, dtype=int)
    embargo = max(0, int(embargo_bars))
    sharpes: list[float] = []
    for window in range(n_windows):
        start = int(cut_points[window])
        end = int(cut_points[window + 1])
        start = min(end, start + embargo)
        if end <= start:
            continue
        segment = pd.Series(values[start:end], index=clean.index[start:end])
        sharpes.append(round(float(annualized_sharpe(segment, periods)), 6))
    if not sharpes:
        return WalkForwardResult([], 0.0, 0.0, 0.0, 0)
    array = np.array(sharpes, dtype=float)
    q75, q25 = np.percentile(array, [75, 25])
    return WalkForwardResult(
        window_test_sharpes=sharpes,
        median_test_sharpe=round(float(np.median(array)), 6),
        iqr_test_sharpe=round(float(q75 - q25), 6),
        positive_window_share=round(float(np.mean(array > 0)), 6),
        n_windows=len(sharpes),
    )
