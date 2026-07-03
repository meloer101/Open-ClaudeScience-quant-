from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PBOResult:
    pbo: float
    n_configs: int
    n_splits: int
    logits: list[float]
    is_overfit: bool


def probability_of_backtest_overfitting(
    returns_matrix: pd.DataFrame,
    *,
    n_splits: int = 16,
) -> PBOResult:
    clean = returns_matrix.replace([np.inf, -np.inf], np.nan).dropna(how="all")
    clean = clean.dropna(axis=1, how="all").fillna(0.0)
    n_configs = int(clean.shape[1])
    n_splits = int(n_splits)
    if n_configs < 4 or n_splits < 4 or len(clean) < n_splits:
        return PBOResult(0.0, n_configs, n_splits, [], False)
    if n_splits % 2:
        n_splits -= 1
    if n_splits < 4:
        return PBOResult(0.0, n_configs, n_splits, [], False)

    cut_points = np.linspace(0, len(clean), n_splits + 1, dtype=int)
    blocks = [clean.iloc[cut_points[index] : cut_points[index + 1]] for index in range(n_splits)]
    logits: list[float] = []
    split_indices = range(n_splits)
    for train_indices in combinations(split_indices, n_splits // 2):
        test_indices = tuple(index for index in split_indices if index not in train_indices)
        train = pd.concat([blocks[index] for index in train_indices])
        test = pd.concat([blocks[index] for index in test_indices])
        train_perf = _sharpe_like(train)
        test_perf = _sharpe_like(test)
        if train_perf.empty or test_perf.empty:
            continue
        winner = train_perf.idxmax()
        ranks = test_perf.rank(method="average", ascending=True)
        relative_rank = float(ranks[winner] / (n_configs + 1.0))
        relative_rank = min(max(relative_rank, 1e-6), 1.0 - 1e-6)
        logits.append(float(np.log(relative_rank / (1.0 - relative_rank))))

    if not logits:
        return PBOResult(0.0, n_configs, n_splits, [], False)
    pbo = float(np.mean([value <= 0.0 for value in logits]))
    return PBOResult(round(pbo, 6), n_configs, n_splits, [round(value, 6) for value in logits], pbo > 0.5)


def _sharpe_like(frame: pd.DataFrame) -> pd.Series:
    std = frame.std(axis=0, ddof=0).replace(0, np.nan)
    values = frame.mean(axis=0).div(std).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return values.astype(float)
