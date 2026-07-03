from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from quantbench.engine.metrics import annualized_sharpe, periods_per_year_from_timestamps
from quantbench.portfolio.combine import CombinedPortfolio, combine
from quantbench.review.beta_exposure import compute_beta
from quantbench.review.regime import yearly_return_contribution
from quantbench.review.report import (
    BETA_ABS_WARNING,
    BETA_R2_WARNING,
    MIN_BETA_OBSERVATIONS,
    PARAMETER_INSTABILITY_THRESHOLD,
    REGIME_CONCENTRATION_THRESHOLD,
    TAIL_DEPENDENCE_SHARE_WARNING,
    TURNOVER_ANNUAL_WARNING,
    ReviewFinding,
    ReviewReport,
    determine_verdict,
)
from quantbench.review.tail_dependence import MAX_BEST_DAYS, best_days_contribution_share

# Thresholds specific to combining strategies rather than to a single factor -
# deliberately separate constants from report.py's (even where the shape of
# the check is similar) since there is no reason weight-perturbation or
# concentration tolerance for a portfolio of factors should move in lockstep
# with the single-factor thresholds if either turns out to need retuning later.
FACTOR_CONCENTRATION_WARNING = 0.5
CORRELATION_HEALTH_WARNING = 0.7
MIN_TRAIN_TEST_OBSERVATIONS = 30


def run_portfolio_review(
    *,
    returns: pd.DataFrame,
    weights: dict[str, float],
    method: str,
    combined: CombinedPortfolio,
    train_returns: pd.Series | None,
    test_returns: pd.Series | None,
    benchmark_returns: pd.Series | None = None,
    benchmark_symbol: str | None = None,
) -> ReviewReport:
    """Portfolio-combination analogue of quantbench.review.report.run_review.

    A combined portfolio has no compute(df) code and no factor_panel, so this
    does not (and cannot) reuse run_review() wholesale. Instead: checks that
    only ever needed a plain return series (regime/tail_dependence/beta_exposure)
    are reused as-is from quantbench.review; checks that were code/panel-specific
    (lookahead, symbol_concentration) are replaced with portfolio-specific
    equivalents (weight_stability in place of parameter_stability,
    factor_concentration in place of symbol_concentration); and two checks that
    only make sense for a combination of pre-existing strategies
    (correlation_health, improvement_over_best_single) are new. The result is
    still a plain ReviewReport, so determine_verdict/to_markdown/manifest
    storage/Critic all keep working unmodified.
    """
    findings: list[ReviewFinding] = [
        _portfolio_out_of_sample_finding(train_returns, test_returns),
        _weight_stability_finding(returns, weights, method),
        _factor_concentration_finding(returns, weights),
        _correlation_health_finding(returns),
        _improvement_over_best_single_finding(returns, weights, combined),
        _regime_finding(combined.returns),
        _tail_finding(combined.returns),
        _turnover_finding(combined.metrics.get("turnover_annual")),
        _beta_finding(combined.returns, benchmark_returns, benchmark_symbol),
    ]
    verdict, reason = determine_verdict(findings)
    return ReviewReport(findings=findings, verdict=verdict, verdict_reason=reason)


def _portfolio_out_of_sample_finding(train_returns: pd.Series | None, test_returns: pd.Series | None) -> ReviewFinding:
    if (
        train_returns is None
        or test_returns is None
        or len(train_returns) < MIN_TRAIN_TEST_OBSERVATIONS
        or len(test_returns) < MIN_TRAIN_TEST_OBSERVATIONS
    ):
        return ReviewFinding(
            "portfolio_out_of_sample", "info", "Not enough train/test observations to evaluate out-of-sample decay.", {}
        )
    train_sharpe = annualized_sharpe(train_returns, periods_per_year_from_timestamps(train_returns.index))
    test_sharpe = annualized_sharpe(test_returns, periods_per_year_from_timestamps(test_returns.index))
    detail = {
        "train_sharpe": round(train_sharpe, 4),
        "test_sharpe": round(test_sharpe, 4),
        "train_observations": len(train_returns),
        "test_observations": len(test_returns),
    }
    if train_sharpe > 0.5 and test_sharpe < 0:
        return ReviewFinding(
            "portfolio_out_of_sample",
            "critical",
            "Portfolio out-of-sample Sharpe flipped negative versus a solidly positive in-sample Sharpe, "
            "using the same fixed weights fit on the in-sample period.",
            detail,
        )
    if train_sharpe > 0 and test_sharpe < 0:
        return ReviewFinding(
            "portfolio_out_of_sample",
            "warning",
            "Portfolio out-of-sample Sharpe flipped negative versus a (weak) positive in-sample Sharpe.",
            detail,
        )
    if train_sharpe > 0 and test_sharpe / train_sharpe < 0.5:
        return ReviewFinding(
            "portfolio_out_of_sample", "critical", "Portfolio out-of-sample Sharpe decayed by more than half versus in-sample.", detail
        )
    if train_sharpe > 0 and test_sharpe / train_sharpe < 0.8:
        return ReviewFinding(
            "portfolio_out_of_sample", "warning", "Portfolio out-of-sample Sharpe decayed materially versus in-sample.", detail
        )
    return ReviewFinding(
        "portfolio_out_of_sample",
        "pass",
        "Portfolio out-of-sample Sharpe did not decay materially versus in-sample, using the same fixed weights.",
        detail,
    )


def _weight_stability_finding(returns: pd.DataFrame, weights: dict[str, float], method: str) -> ReviewFinding:
    def _sharpe_for(w: dict[str, float]) -> float:
        return combine(returns, w, cost_bps=0.0).metrics["sharpe"]

    base_sharpe = _sharpe_for(weights)
    sharpes = [base_sharpe]
    for name, base_value in weights.items():
        for direction in (0.8, 1.2):
            perturbed = dict(weights)
            perturbed[name] = base_value * direction
            total = sum(perturbed.values())
            if total <= 0:
                continue
            perturbed = {key: value / total for key, value in perturbed.items()}
            sharpes.append(_sharpe_for(perturbed))
    spread = max(sharpes) - min(sharpes)
    detail = {"base_sharpe": round(base_sharpe, 4), "perturbed_sharpe_spread": round(spread, 4), "method": method}
    if spread > PARAMETER_INSTABILITY_THRESHOLD:
        return ReviewFinding(
            "weight_stability", "warning", "Portfolio Sharpe is sensitive to +/-20% perturbations of individual factor weights.", detail
        )
    return ReviewFinding("weight_stability", "pass", "Weight perturbation did not breach the instability threshold.", detail)


def _factor_concentration_finding(returns: pd.DataFrame, weights: dict[str, float]) -> ReviewFinding:
    names = [name for name in returns.columns if name in weights]
    if len(names) < 2:
        return ReviewFinding("factor_concentration", "info", "Only one constituent factor; concentration check is not meaningful.", {})

    cov = returns[names].cov().to_numpy()
    w = np.array([weights[name] for name in names])
    max_weight = float(np.max(w))
    port_var = float(w @ cov @ w)

    if port_var <= 0:
        rc_share = {name: None for name in names}
        top_name, top_share = names[int(np.argmax(w))], max_weight
    else:
        marginal = cov @ w
        rc = w * marginal
        total = rc.sum()
        rc_share_arr = rc / total if total != 0 else np.zeros_like(rc)
        rc_share = {name: round(float(share), 4) for name, share in zip(names, rc_share_arr)}
        top_idx = int(np.argmax(np.abs(rc_share_arr)))
        top_name, top_share = names[top_idx], float(abs(rc_share_arr[top_idx]))

    detail = {
        "risk_contribution_share": rc_share,
        "top_risk_contributor": top_name,
        "top_risk_contribution_share": round(top_share, 4),
        "max_single_weight": round(max_weight, 4),
    }
    if top_share > FACTOR_CONCENTRATION_WARNING:
        return ReviewFinding(
            "factor_concentration", "warning", f"Portfolio risk is concentrated in a single factor ({top_name}).", detail
        )
    if max_weight >= 0.999:
        return ReviewFinding(
            "factor_concentration",
            "warning",
            f"A single factor ({names[int(np.argmax(w))]}) received essentially the entire weight allocation.",
            detail,
        )
    return ReviewFinding("factor_concentration", "pass", "Portfolio risk contribution is not dominated by a single factor.", detail)


def _correlation_health_finding(returns: pd.DataFrame) -> ReviewFinding:
    if returns.shape[1] < 2:
        return ReviewFinding("correlation_health", "info", "Only one constituent factor; correlation check is not meaningful.", {})
    names = list(returns.columns)
    corr = returns.corr().to_numpy()
    n = corr.shape[0]
    off_diag = corr[~np.eye(n, dtype=bool)]
    avg_corr = float(np.mean(off_diag)) if len(off_diag) else 0.0

    # A signed average across all pairs can hide one badly-redundant pair: with
    # e.g. A/B at 0.99 and C independent of both, the three-way average can sit
    # well under the threshold even though A and B are almost the same factor.
    # Tracking the single worst |pairwise correlation| catches that case even
    # when the average looks fine.
    max_abs_corr = 0.0
    max_pair: tuple[str, str] | None = None
    for i in range(n):
        for j in range(i + 1, n):
            value = abs(float(corr[i, j]))
            if value > max_abs_corr:
                max_abs_corr = value
                max_pair = (names[i], names[j])

    detail = {
        "average_pairwise_correlation": round(avg_corr, 4),
        "max_pairwise_abs_correlation": round(max_abs_corr, 4),
        "max_correlated_pair": list(max_pair) if max_pair else None,
    }
    if avg_corr > CORRELATION_HEALTH_WARNING:
        return ReviewFinding(
            "correlation_health",
            "warning",
            "Constituent factors are highly correlated with each other on average; the diversification benefit of combining them is limited.",
            detail,
        )
    if max_abs_corr > CORRELATION_HEALTH_WARNING and max_pair is not None:
        return ReviewFinding(
            "correlation_health",
            "warning",
            f"{max_pair[0]} and {max_pair[1]} are highly correlated with each other (|corr|={max_abs_corr:.2f}) even "
            "though the average pairwise correlation looks fine - they are largely redundant with each other.",
            detail,
        )
    return ReviewFinding("correlation_health", "pass", "Constituent factors are not overly correlated with each other.", detail)


def _improvement_over_best_single_finding(returns: pd.DataFrame, weights: dict[str, float], combined: CombinedPortfolio) -> ReviewFinding:
    names = [name for name in returns.columns if name in weights]
    best_name: str | None = None
    best_sharpe: float | None = None
    for name in names:
        series = returns[name].dropna()
        if series.empty:
            continue
        sharpe = annualized_sharpe(series, periods_per_year_from_timestamps(series.index))
        if best_sharpe is None or sharpe > best_sharpe:
            best_sharpe, best_name = sharpe, name

    portfolio_sharpe = combined.metrics.get("sharpe", 0.0) or 0.0
    detail = {
        "best_single_factor": best_name,
        "best_single_sharpe": round(best_sharpe, 4) if best_sharpe is not None else None,
        "portfolio_sharpe": portfolio_sharpe,
    }
    if best_sharpe is not None and portfolio_sharpe <= best_sharpe:
        return ReviewFinding(
            "improvement_over_best_single",
            "warning",
            f"Portfolio Sharpe does not improve on its best single constituent factor ({best_name}); "
            "combining these factors added no measurable value over just using that one.",
            detail,
        )
    return ReviewFinding(
        "improvement_over_best_single", "pass", "Portfolio Sharpe improves on its best single constituent factor.", detail
    )


# The three checks below only ever operate on a plain return series (plus,
# for beta, a benchmark series) - identical to their single-factor
# counterparts in quantbench/review/report.py, just renamed locally to make
# clear they're being applied to the combined portfolio's own return series
# rather than a single factor's.


def _regime_finding(returns: pd.Series) -> ReviewFinding:
    contributions = yearly_return_contribution(returns)
    if len(contributions) < 2:
        return ReviewFinding(
            "regime", "info", "Data does not cover enough calendar years to evaluate regime dependence.", {"yearly_contribution": contributions}
        )
    year, contribution = max(contributions.items(), key=lambda item: abs(item[1]))
    detail = {"yearly_contribution": contributions, "max_year": year, "max_abs_contribution": abs(contribution)}
    if abs(contribution) > REGIME_CONCENTRATION_THRESHOLD:
        return ReviewFinding("regime", "warning", f"Portfolio return contribution is concentrated in {year}.", detail)
    return ReviewFinding("regime", "pass", "No single calendar year dominates portfolio return contribution.", detail)


def _tail_finding(returns: pd.Series) -> ReviewFinding:
    if len(returns.dropna()) < 20:
        return ReviewFinding("tail_dependence", "info", "Not enough return observations to evaluate tail dependence.", {})
    share = best_days_contribution_share(returns)
    detail = {"best_days_positive_return_share": share}
    if share > TAIL_DEPENDENCE_SHARE_WARNING:
        return ReviewFinding(
            "tail_dependence",
            "warning",
            f"The best handful of days (up to {MAX_BEST_DAYS}) account for {share:.0%} of all positive portfolio daily return.",
            detail,
        )
    return ReviewFinding("tail_dependence", "pass", "Positive portfolio return is not concentrated in the best 5% of days.", detail)


def _turnover_finding(turnover_annual: float | None) -> ReviewFinding:
    detail: dict[str, Any] = {"turnover_annual": turnover_annual}
    if turnover_annual is None:
        return ReviewFinding("turnover", "info", "Turnover metric was unavailable.", detail)
    if turnover_annual > TURNOVER_ANNUAL_WARNING:
        return ReviewFinding("turnover", "warning", "Annualized rebalancing turnover is high enough to raise implementation concerns.", detail)
    return ReviewFinding("turnover", "pass", "Annualized rebalancing turnover is below the reviewer warning threshold.", detail)


def _beta_finding(returns: pd.Series, benchmark_returns: pd.Series | None, benchmark_symbol: str | None) -> ReviewFinding:
    if benchmark_returns is None or benchmark_returns.empty:
        detail = {"benchmark_symbol": benchmark_symbol} if benchmark_symbol else {}
        return ReviewFinding("beta_exposure", "info", "Benchmark returns unavailable; beta exposure check skipped.", detail)
    beta, r_squared, observations = compute_beta(returns, benchmark_returns)
    detail = {"beta": beta, "r_squared": r_squared, "observations": observations}
    if benchmark_symbol:
        detail["benchmark_symbol"] = benchmark_symbol
    if observations < MIN_BETA_OBSERVATIONS:
        return ReviewFinding("beta_exposure", "info", "Not enough aligned benchmark observations to evaluate beta exposure.", detail)
    if r_squared > BETA_R2_WARNING and abs(beta) > BETA_ABS_WARNING:
        return ReviewFinding("beta_exposure", "warning", "Portfolio returns are substantially explained by benchmark beta exposure.", detail)
    return ReviewFinding("beta_exposure", "pass", "Benchmark beta exposure did not breach warning thresholds.", detail)
