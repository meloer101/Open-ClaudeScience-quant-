from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from quantbench.engine.metrics import annualized_return, annualized_sharpe, compute_drawdown, periods_per_year_from_timestamps


@dataclass(frozen=True)
class CombinedPortfolio:
    returns: pd.Series
    equity_curve: pd.Series
    drawdown: pd.Series
    turnover: pd.Series
    metrics: dict[str, float]

    def to_json_dict(self) -> dict[str, Any]:
        # Same shape as BacktestResult.to_json_dict() / CrossSectionalBacktestResult.to_json_dict()
        # (quantbench/engine/{vectorized_backtest,cross_sectional_backtest}.py) so
        # every reader that already knows how to load a run's own return series -
        # run_reader.read_returns_series, library/compare.py's correlation matrix,
        # ChartsPanel - works on a portfolio run without any special-casing.
        return {
            "metrics": self.metrics,
            "series": {
                "timestamp": [str(item) for item in self.returns.index],
                "returns": self.returns.fillna(0).round(10).tolist(),
                "equity_curve": self.equity_curve.round(10).tolist(),
                "drawdown": self.drawdown.round(10).tolist(),
                "turnover": self.turnover.reindex(self.returns.index).fillna(0).round(6).tolist(),
            },
        }


def combine(returns: pd.DataFrame, weights: dict[str, float], cost_bps: float = 0.0) -> CombinedPortfolio:
    """Combines constituent factor return series into one portfolio return
    series under a fixed target weight vector.

    Each column of `returns` is itself already a net strategy return series
    (e.g. a cross-sectional long-short return, or a single-symbol signal
    return) - not an asset price return - so "combining" means holding each
    strategy at its target weight and rebalancing back to that target every
    period, exactly as a constant-mix multi-strategy allocation would in
    practice. Turnover is derived from how far weights drift from target
    within a period before the next rebalance, using the same
    `net = gross - turnover * cost_bps / 10000` convention as
    engine/cross_sectional_backtest.py, not invented separately.
    """
    if returns.empty:
        raise ValueError("returns is empty")
    ordered = [name for name in returns.columns if name in weights]
    if not ordered:
        raise ValueError("no weight keys match the columns of returns")

    weight_series = pd.Series({name: weights[name] for name in ordered})
    aligned = returns[ordered].fillna(0.0)

    gross_returns = aligned.mul(weight_series, axis=1).sum(axis=1)

    # Weights drift within each period as constituents earn different returns;
    # rebalancing back to the fixed target at the next period boundary costs
    # half the L1 drift (buy on one side, sell on the other). The first period
    # starts exactly at target by construction, so it has no rebalance cost -
    # shift(1) attributes period t's cost to the drift that accumulated during
    # period t-1, mirroring how run_cross_sectional_backtest applies the same
    # period's turnover to that period's net return.
    growth = 1 + aligned
    port_growth = 1 + gross_returns
    drifted = growth.mul(weight_series, axis=1).div(port_growth, axis=0)
    turnover = (0.5 * (drifted - weight_series).abs().sum(axis=1)).shift(1).fillna(0.0)

    net_returns = gross_returns - turnover * cost_bps / 10000
    equity_curve = (1 + net_returns.fillna(0)).cumprod()
    drawdown = compute_drawdown(equity_curve)
    ppy = periods_per_year_from_timestamps(net_returns.index)

    weighted_vol = float((weight_series.abs() * aligned.std(ddof=0)).sum())
    gross_vol = float(gross_returns.std(ddof=0))
    diversification_ratio = weighted_vol / gross_vol if gross_vol > 0 else None

    metrics = {
        "sharpe": round(annualized_sharpe(net_returns, ppy), 6),
        "annual_return": round(annualized_return(net_returns, ppy), 6),
        "max_drawdown": round(float(drawdown.min()), 6),
        "turnover_annual": round(float(turnover.mean() * ppy), 6),
        "diversification_ratio": round(diversification_ratio, 6) if diversification_ratio is not None else None,
        "n_factors": len(ordered),
        "observations": int(len(net_returns)),
    }

    return CombinedPortfolio(
        returns=net_returns,
        equity_curve=equity_curve,
        drawdown=drawdown,
        turnover=turnover,
        metrics=metrics,
    )
