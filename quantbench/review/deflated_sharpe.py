from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import norm

from quantbench.engine.metrics import annualized_sharpe


EULER_MASCHERONI = 0.5772156649015329
MIN_DSR_OBSERVATIONS = 30
DSR_SIGNIFICANCE_THRESHOLD = 0.95


@dataclass(frozen=True)
class DeflatedSharpeResult:
    observed_sharpe: float
    deflated_sharpe: float
    expected_max_sharpe: float
    n_trials: int
    sharpe_std_across_trials: float
    n_observations: int
    skew: float
    kurtosis: float
    is_significant: bool


def deflated_sharpe_ratio(
    returns: pd.Series,
    *,
    n_trials: int,
    trial_sharpes: list[float] | None = None,
    periods_per_year: float,
) -> DeflatedSharpeResult:
    clean = pd.Series(returns, dtype="float64").replace([np.inf, -np.inf], np.nan).dropna()
    n_observations = int(len(clean))
    n_trials = max(int(n_trials), 1)
    observed = annualized_sharpe(clean, periods_per_year)
    observed_periodic = _periodic_sharpe(clean)
    if n_observations < MIN_DSR_OBSERVATIONS:
        return DeflatedSharpeResult(
            observed_sharpe=round(float(observed), 6),
            deflated_sharpe=0.0,
            expected_max_sharpe=0.0,
            n_trials=n_trials,
            sharpe_std_across_trials=0.0,
            n_observations=n_observations,
            skew=0.0,
            kurtosis=0.0,
            is_significant=False,
        )

    skew = float(clean.skew()) if n_observations >= 3 else 0.0
    kurtosis = float(clean.kurt()) + 3.0 if n_observations >= 4 else 3.0
    sr_std = _sharpe_std(clean, observed_periodic, skew, kurtosis, n_observations, trial_sharpes, periods_per_year)
    expected_max_periodic = _expected_max_sharpe(n_trials, sr_std)
    denominator = 1.0 - skew * observed_periodic + ((kurtosis - 1.0) / 4.0) * observed_periodic**2
    denominator = max(float(denominator), 1e-12)
    z_score = (observed_periodic - expected_max_periodic) * np.sqrt(n_observations - 1) / np.sqrt(denominator)
    probability = float(norm.cdf(z_score))
    expected_max = expected_max_periodic * np.sqrt(periods_per_year)
    return DeflatedSharpeResult(
        observed_sharpe=round(float(observed), 6),
        deflated_sharpe=round(probability, 6),
        expected_max_sharpe=round(float(expected_max), 6),
        n_trials=n_trials,
        sharpe_std_across_trials=round(float(sr_std), 6),
        n_observations=n_observations,
        skew=round(skew, 6),
        kurtosis=round(kurtosis, 6),
        is_significant=probability > DSR_SIGNIFICANCE_THRESHOLD,
    )


def _sharpe_std(
    returns: pd.Series,
    observed_periodic_sharpe: float,
    skew: float,
    kurtosis: float,
    n_observations: int,
    trial_sharpes: list[float] | None,
    periods_per_year: float,
) -> float:
    annualization = np.sqrt(periods_per_year) if periods_per_year > 0 else 1.0
    clean_trial_sharpes = [float(value) / annualization for value in trial_sharpes or [] if np.isfinite(value)]
    if len(clean_trial_sharpes) >= 2:
        std = float(np.std(clean_trial_sharpes, ddof=1))
        if std > 0:
            return std
    denominator = max(n_observations - 1, 1)
    variance = (
        1.0
        - skew * observed_periodic_sharpe
        + ((kurtosis - 1.0) / 4.0) * observed_periodic_sharpe**2
    ) / denominator
    return float(np.sqrt(max(variance, 1e-12)))


def _expected_max_sharpe(n_trials: int, sharpe_std: float) -> float:
    if n_trials <= 1 or sharpe_std <= 0:
        return 0.0
    first = norm.ppf(1.0 - 1.0 / n_trials)
    second = norm.ppf(1.0 - 1.0 / (n_trials * np.e))
    return float(sharpe_std * ((1.0 - EULER_MASCHERONI) * first + EULER_MASCHERONI * second))


def _periodic_sharpe(returns: pd.Series) -> float:
    std = float(returns.std(ddof=0))
    if std == 0.0:
        return 0.0
    return float(returns.mean() / std)
