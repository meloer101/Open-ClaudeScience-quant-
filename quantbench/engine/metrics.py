import numpy as np
import pandas as pd


def periods_per_year(time_delta: pd.Timedelta) -> float:
    if time_delta <= pd.Timedelta(0):
        return 365 * 6
    return pd.Timedelta(days=365) / time_delta


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
