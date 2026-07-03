from dataclasses import asdict, dataclass
import math

import numpy as np
import pandas as pd
from scipy.stats import norm


DEFAULT_PERIODS_PER_YEAR = 252.0


def periods_per_year_from_timestamps(timestamps) -> float:
    """Infer the annualization factor from how densely bars actually occur.

    Using the *median gap between bars* looks right but silently breaks for
    market-hours-only assets: weekends make the calendar span between two
    consecutive equity bars look "the same" as a crypto bar's calendar span,
    even though far fewer bars occur per year (252 trading days vs 365
    calendar days) - inflating Sharpe by ~sqrt(365/252) ≈ 1.20x. Counting
    actual observed bars per unit of calendar time sidesteps this: it comes
    out to ~252/yr for equities daily bars and ~2190/yr for 4h crypto bars
    without needing to special-case the asset class.
    """
    ts = pd.to_datetime(pd.Index(timestamps), utc=True).dropna().unique()
    ts = pd.Index(ts).sort_values()
    if len(ts) < 2:
        return DEFAULT_PERIODS_PER_YEAR
    span_days = (ts[-1] - ts[0]) / pd.Timedelta(days=1)
    if span_days <= 0:
        return DEFAULT_PERIODS_PER_YEAR
    bars_per_day = (len(ts) - 1) / span_days
    ppy = bars_per_day * 365.25
    return float(ppy) if ppy > 0 else DEFAULT_PERIODS_PER_YEAR


def annualized_sharpe(returns: pd.Series, periods: float) -> float:
    clean = returns.replace([np.inf, -np.inf], np.nan).dropna()
    if clean.empty or clean.std(ddof=0) == 0:
        return 0.0
    return float(clean.mean() / clean.std(ddof=0) * np.sqrt(periods))


def annualized_return(returns: pd.Series, periods: float) -> float:
    clean = returns.fillna(0)
    if clean.empty:
        return 0.0
    total = float((1 + clean).prod())
    years = max(len(clean) / periods, 1 / periods)
    return float(total ** (1 / years) - 1)


def compute_drawdown(equity_curve: pd.Series) -> pd.Series:
    running_max = equity_curve.cummax()
    return equity_curve / running_max - 1


def information_coefficient(signal: pd.Series, forward_returns: pd.Series) -> float:
    joined = pd.concat([signal, forward_returns], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    if len(joined) < 3:
        return 0.0
    corr = joined.iloc[:, 0].corr(joined.iloc[:, 1], method="spearman")
    return 0.0 if pd.isna(corr) else float(corr)


@dataclass(frozen=True)
class ICSignificance:
    ic_mean: float
    ic_std: float
    t_stat: float
    p_value: float
    n_periods: int
    nw_lags: int
    is_significant: bool

    def to_dict(self) -> dict[str, float | int | bool]:
        return asdict(self)


def ic_newey_west(ic_series: pd.Series, *, lags: int | None = None) -> ICSignificance:
    clean = pd.Series(ic_series, dtype="float64").replace([np.inf, -np.inf], np.nan).dropna()
    n_periods = int(len(clean))
    if n_periods < 10:
        return ICSignificance(0.0, 0.0, float("nan"), 1.0, n_periods, 0 if lags is None else max(0, int(lags)), False)

    values = clean.to_numpy(dtype=float)
    mean = float(np.mean(values))
    std = float(np.std(values, ddof=1))
    max_lags = max(0, n_periods - 1)
    nw_lags = int(math.floor(4 * (n_periods / 100) ** (2 / 9))) if lags is None else int(lags)
    nw_lags = max(0, min(nw_lags, max_lags))

    centered = values - mean
    gamma0 = float(np.dot(centered, centered) / n_periods)
    hac_var = gamma0
    for lag in range(1, nw_lags + 1):
        covariance = float(np.dot(centered[lag:], centered[:-lag]) / n_periods)
        weight = 1.0 - lag / (nw_lags + 1)
        hac_var += 2.0 * weight * covariance
    hac_var = max(hac_var, 0.0)
    if hac_var <= 0:
        t_stat = float("inf") if mean > 0 else float("-inf") if mean < 0 else 0.0
        p_value = 0.0 if mean != 0 else 1.0
    else:
        t_stat = float(mean / math.sqrt(hac_var / n_periods))
        p_value = float(2.0 * norm.sf(abs(t_stat)))
    return ICSignificance(
        ic_mean=round(mean, 6),
        ic_std=round(std, 6),
        t_stat=round(t_stat, 6) if math.isfinite(t_stat) else t_stat,
        p_value=round(p_value, 6),
        n_periods=n_periods,
        nw_lags=nw_lags,
        is_significant=bool(abs(t_stat) > 1.96),
    )


def monotonicity_score(values: pd.Series) -> float:
    clean = values.replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) < 2:
        return 0.0
    diffs = clean.diff().dropna()
    if diffs.empty:
        return 0.0
    direction = 1 if clean.iloc[-1] >= clean.iloc[0] else -1
    return float((diffs.mul(direction) >= 0).mean())


# Phase 0 has no Reviewer Agent yet (see Phase 2), but a backtest this implausible
# should never be reported without a loud caveat. These thresholds are deliberately
# generous (real strategies essentially never clear them) so this only fires on
# clearly broken inputs (e.g. synthetic fallback data, a backtest alignment bug).
SANITY_SHARPE_LIMIT = 10.0
SANITY_ANNUAL_RETURN_LIMIT = 5.0  # 500%


def sanity_check_metrics(metrics: dict[str, float]) -> list[str]:
    warnings: list[str] = []
    sharpe = metrics.get("sharpe", 0.0)
    annual_return = metrics.get("annual_return", 0.0)
    if abs(sharpe) > SANITY_SHARPE_LIMIT:
        warnings.append(
            f"Sharpe={sharpe:.2f} exceeds plausible range (|Sharpe|>{SANITY_SHARPE_LIMIT}). "
            "This almost always means the data or backtest alignment is broken, not that "
            "the strategy is genuinely this good."
        )
    if abs(annual_return) > SANITY_ANNUAL_RETURN_LIMIT:
        warnings.append(
            f"Annualized return={annual_return:.2%} exceeds plausible range "
            f"(|return|>{SANITY_ANNUAL_RETURN_LIMIT:.0%}). Treat this result as invalid "
            "until the data source and backtest logic are verified."
        )
    return warnings
