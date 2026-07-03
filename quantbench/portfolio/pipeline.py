from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from quantbench.portfolio.combine import CombinedPortfolio, combine
from quantbench.portfolio.optimize import PORTFOLIO_METHODS, OptimizationResult, evaluate_all_methods
from quantbench.portfolio.review import run_portfolio_review
from quantbench.review.report import ReviewReport


@dataclass(frozen=True)
class PortfolioOptimizationOutcome:
    selected_method: str
    weights: dict[str, float]
    combined: CombinedPortfolio
    review_report: ReviewReport
    comparison_table: dict[str, dict[str, Any]]
    correlation: dict[str, dict[str, float]]
    train_test_split_index: str
    overlap_observations: int


def run_portfolio_pipeline(
    returns_by_run: dict[str, pd.Series],
    *,
    method: str,
    cost_bps: float,
    split: float,
    max_weight: float,
    benchmark_returns: pd.Series | None = None,
    benchmark_symbol: str | None = None,
) -> PortfolioOptimizationOutcome:
    """Pure orchestration: given each constituent run's own return series
    (already read from disk by the caller), fits weights on a training slice,
    evaluates every method for the honest in-sample-vs-out-of-sample
    comparison table, builds the full-sample combined portfolio under the
    selected method's train-fit weights, and runs the portfolio-specific
    Reviewer. No filesystem or artifact writes happen here - the caller
    (quantbench.agent.coordinator) owns creating the Run and persisting
    everything this returns, exactly as it does for run_cross_sectional_backtest
    and screen_factors.
    """
    if method not in PORTFOLIO_METHODS:
        raise ValueError(f"unknown portfolio method: {method!r}, expected one of {PORTFOLIO_METHODS}")

    aligned = _align_returns(returns_by_run)
    if aligned.shape[1] < 2:
        raise ValueError("portfolio optimization requires at least 2 run_ids with overlapping return series")

    train, test = _train_test_split(aligned, split)
    optimized = evaluate_all_methods(train, max_weight=max_weight)
    comparison_table = _build_comparison_table(optimized, train, test)
    # The selected method's headline weights always come from the optimizer's
    # own OptimizationResult, never from comparison_table (which rounds
    # weights to 6dp purely for JSON/display readability) - combine() below
    # and the Reviewer both need the un-rounded values.
    weights = optimized[method].weights

    # Full-sample metrics/equity curve are computed under the weights fit on
    # the training slice only - never refit on the full sample - so the
    # headline numbers reported for this run are never circular with the
    # honesty check in _portfolio_out_of_sample_finding below. This mirrors
    # how run_review's own out-of-sample check works: the reported metrics
    # come from the real run, and OOS decay is a *separate* diagnostic.
    full_combined = combine(aligned, weights, cost_bps=cost_bps)
    train_combined_returns = combine(train, weights, cost_bps=0.0).returns
    test_combined_returns = combine(test, weights, cost_bps=0.0).returns if len(test) >= 2 else None

    review_report = run_portfolio_review(
        returns=aligned,
        weights=weights,
        method=method,
        combined=full_combined,
        train_returns=train_combined_returns,
        test_returns=test_combined_returns,
        benchmark_returns=benchmark_returns,
        benchmark_symbol=benchmark_symbol,
    )

    correlation = {str(k): {str(k2): (None if pd.isna(v2) else round(float(v2), 4)) for k2, v2 in v.items()} for k, v in aligned.corr().to_dict().items()}

    return PortfolioOptimizationOutcome(
        selected_method=method,
        weights=weights,
        combined=full_combined,
        review_report=review_report,
        comparison_table=comparison_table,
        correlation=correlation,
        train_test_split_index=str(train.index[-1]) if len(train) else "",
        overlap_observations=len(aligned),
    )


def _align_returns(returns_by_run: dict[str, pd.Series]) -> pd.DataFrame:
    df = pd.DataFrame(returns_by_run)
    return df.sort_index().dropna(how="any")


def _train_test_split(returns: pd.DataFrame, split: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    n = len(returns)
    cut = max(1, min(n - 1, int(round(n * split))))
    return returns.iloc[:cut], returns.iloc[cut:]


def _build_comparison_table(
    optimized: dict[str, OptimizationResult], train: pd.DataFrame, test: pd.DataFrame
) -> dict[str, dict[str, Any]]:
    table: dict[str, dict[str, Any]] = {}
    for method, result in optimized.items():
        train_combined = combine(train, result.weights, cost_bps=0.0)
        test_combined = combine(test, result.weights, cost_bps=0.0) if len(test) >= 2 else None
        table[method] = {
            # Rounded here purely for JSON/display readability - callers must
            # use `optimized[method].weights` (unrounded) for any further
            # computation, not this copy.
            "weights": {name: round(value, 6) for name, value in result.weights.items()},
            "diagnostics": result.diagnostics,
            "train_sharpe": train_combined.metrics["sharpe"],
            "test_sharpe": test_combined.metrics["sharpe"] if test_combined else None,
            "train_observations": len(train),
            "test_observations": len(test),
        }
    return table
