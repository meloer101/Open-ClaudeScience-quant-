from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class WalkForwardResult:
    window_test_sharpes: list[float]
    median_test_sharpe: float
    iqr_test_sharpe: float
    positive_window_share: float
    n_windows: int


def run_walk_forward(
    data: pd.DataFrame,
    run_on_data: Callable[[pd.DataFrame], dict[str, float]],
    *,
    n_windows: int = 4,
    embargo_bars: int = 0,
) -> WalkForwardResult:
    if n_windows < 1 or data.empty or len(data) < n_windows:
        return WalkForwardResult([], 0.0, 0.0, 0.0, 0)
    ordered = data.sort_values("timestamp").reset_index(drop=True) if "timestamp" in data.columns else data.reset_index(drop=True)
    cut_points = np.linspace(0, len(ordered), n_windows + 1, dtype=int)
    windows = [ordered.iloc[cut_points[index] : cut_points[index + 1]] for index in range(n_windows)]
    sharpes: list[float] = []
    for window in windows:
        if embargo_bars > 0:
            window = window.iloc[embargo_bars:]
        if window.empty:
            continue
        metrics = run_on_data(window.copy())
        sharpes.append(round(float(metrics.get("sharpe", 0.0) or 0.0), 6))
    if not sharpes:
        return WalkForwardResult([], 0.0, 0.0, 0.0, 0)
    values = np.array(sharpes, dtype=float)
    q75, q25 = np.percentile(values, [75, 25])
    return WalkForwardResult(
        window_test_sharpes=sharpes,
        median_test_sharpe=round(float(np.median(values)), 6),
        iqr_test_sharpe=round(float(q75 - q25), 6),
        positive_window_share=round(float(np.mean(values > 0)), 6),
        n_windows=len(sharpes),
    )
