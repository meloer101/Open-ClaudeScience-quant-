from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
import math

import numpy as np
import pandas as pd

from quantbench.engine.metrics import annualized_sharpe, periods_per_year_from_timestamps


@dataclass(frozen=True)
class CPCVResult:
    path_test_sharpes: list[float]
    median_test_sharpe: float
    iqr_test_sharpe: float
    p05_test_sharpe: float
    positive_path_share: float
    n_paths: int
    n_groups: int
    purge_bars: int
    embargo_bars: int


def run_cpcv(
    returns: pd.Series,
    *,
    n_groups: int = 6,
    lookback_bars: int = 0,
    embargo_frac: float = 0.01,
) -> CPCVResult:
    """Combinatorial *purged* cross-validation over a period return series.

    Operates on the already-computed per-period portfolio returns (timestamp
    indexed), not on a recomputed factor. This matters for two reasons the
    earlier draft got wrong:

    * **No seam artifacts / no panel scramble.** Recomputing a rolling factor on
      a concatenation of non-adjacent time blocks computes the lookback across
      the seams; slicing a long cross-sectional panel by row position also cuts
      through a single timestamp's cross-section. Subsetting an already-computed
      period return series sidesteps both - a return at time ``t`` keeps the
      value it truly had, and we only ever *select* periods, never recompute.
    * **Purge/embargo actually bite.** A test period is kept only if its whole
      ``[t - purge, t + embargo]`` neighborhood is also a test period; any period
      whose lookback window reaches into a train (non-test) block is dropped.
      Widening ``lookback_bars`` therefore drops more boundary periods and
      changes the OOS Sharpe - the "P" in CPCV is a real effect, not a label.
    """
    clean = pd.Series(returns, dtype="float64").replace([np.inf, -np.inf], np.nan).dropna()
    purge_bars = max(0, int(lookback_bars))
    n = int(len(clean))
    embargo_bars = max(0, int(math.ceil(max(0.0, embargo_frac) * n)))
    if n_groups < 4 or n_groups % 2 != 0 or n < n_groups:
        return _empty(n_groups, purge_bars, embargo_bars)

    periods = periods_per_year_from_timestamps(clean.index)
    values = clean.to_numpy(dtype=float)
    cut_points = np.linspace(0, n, n_groups + 1, dtype=int)
    group_of = np.empty(n, dtype=int)
    for group in range(n_groups):
        group_of[cut_points[group] : cut_points[group + 1]] = group

    sharpes: list[float] = []
    for test_groups in combinations(range(n_groups), n_groups // 2):
        is_test = np.isin(group_of, test_groups)
        kept: list[int] = []
        for position in np.flatnonzero(is_test):
            low = max(0, position - purge_bars)
            high = min(n - 1, position + embargo_bars)
            if is_test[low : high + 1].all():
                kept.append(int(position))
        if len(kept) < 2:
            continue
        path_returns = pd.Series(values[kept], index=clean.index[kept])
        sharpes.append(round(float(annualized_sharpe(path_returns, periods)), 6))

    if not sharpes:
        return _empty(n_groups, purge_bars, embargo_bars)
    array = np.array(sharpes, dtype=float)
    q75, q25 = np.percentile(array, [75, 25])
    return CPCVResult(
        path_test_sharpes=sharpes,
        median_test_sharpe=round(float(np.median(array)), 6),
        iqr_test_sharpe=round(float(q75 - q25), 6),
        p05_test_sharpe=round(float(np.percentile(array, 5)), 6),
        positive_path_share=round(float(np.mean(array > 0)), 6),
        n_paths=len(sharpes),
        n_groups=n_groups,
        purge_bars=purge_bars,
        embargo_bars=embargo_bars,
    )


def _empty(n_groups: int, purge_bars: int, embargo_bars: int) -> CPCVResult:
    return CPCVResult([], 0.0, 0.0, 0.0, 0.0, 0, n_groups, max(0, int(purge_bars)), max(0, int(embargo_bars)))
