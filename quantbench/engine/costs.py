from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from quantbench.engine.metrics import annualized_sharpe, periods_per_year_from_timestamps


@dataclass(frozen=True)
class LiquidityCostConfig:
    aum_usd: float = 1_000_000
    participation_cap: float = 0.02
    spread_tiers_bps: tuple[tuple[float, float], ...] = (
        (1e9, 2.0),
        (1e8, 8.0),
        (0.0, 20.0),
    )


@dataclass(frozen=True)
class BorrowCostConfig:
    enabled: bool = False
    borrow_tiers_annual: tuple[tuple[float, float], ...] = (
        (1e9, 0.01),
        (1e8, 0.03),
        (0.0, 0.12),
    )
    periods_per_year: float = 252.0


def apply_liquidity_costs(
    weights: pd.DataFrame,
    dollar_volume: pd.DataFrame,
    config: LiquidityCostConfig,
) -> tuple[pd.DataFrame, pd.Series]:
    if weights.empty:
        return weights.copy(), pd.Series(dtype="float64")
    aligned_dv = dollar_volume.reindex(index=weights.index, columns=weights.columns).astype(float)
    target_dollars = weights.abs() * float(config.aum_usd)
    max_dollars = aligned_dv.fillna(0.0).clip(lower=0.0) * float(config.participation_cap)
    fill_ratio = (max_dollars / target_dollars.replace(0.0, np.nan)).clip(upper=1.0).fillna(1.0)
    actual_weights = weights * fill_ratio

    turnover = actual_weights.diff().abs()
    if len(actual_weights):
        turnover.iloc[0] = actual_weights.iloc[0].abs()
    turnover = turnover.fillna(0.0)
    spreads = aligned_dv.apply(lambda col: col.map(lambda value: _spread_bps(float(value), config.spread_tiers_bps) / 2.0 / 10000.0))
    costs = (turnover * spreads.fillna(0.0)).sum(axis=1)
    return actual_weights, costs


def capacity_curve(
    gross_returns: pd.Series,
    weights: pd.DataFrame,
    dollar_volume: pd.DataFrame,
    config: LiquidityCostConfig,
    *,
    aum_grid: tuple[float, ...] = (1e5, 1e6, 1e7, 1e8),
) -> list[dict[str, float]]:
    base_abs = weights.abs().sum(axis=1).replace(0.0, np.nan)
    rows: list[dict[str, float]] = []
    for aum in aum_grid:
        actual, costs = apply_liquidity_costs(weights, dollar_volume, replace(config, aum_usd=float(aum)))
        fill = (actual.abs().sum(axis=1) / base_abs).replace([np.inf, -np.inf], np.nan).fillna(1.0).clip(upper=1.0)
        net = gross_returns.reindex(weights.index).fillna(0.0) * fill - costs.reindex(weights.index).fillna(0.0)
        raw_sharpe = annualized_sharpe(net, periods_per_year_from_timestamps(net.index))
        average_fill = float(fill.mean()) if len(fill) else 1.0
        rows.append(
            {
                "aum_usd": float(aum),
                "sharpe": round(raw_sharpe * average_fill, 6),
                "raw_sharpe": round(raw_sharpe, 6),
                "average_fill_ratio": round(average_fill, 6),
                "total_liquidity_cost": round(float(costs.sum()), 6),
            }
        )
    return rows


def borrow_rates_from_dollar_volume(
    dollar_volume: pd.DataFrame,
    config: BorrowCostConfig,
) -> pd.DataFrame:
    if dollar_volume.empty or not config.enabled:
        return pd.DataFrame(index=dollar_volume.index, columns=dollar_volume.columns, dtype="float64").fillna(0.0)
    daily_rates = dollar_volume.astype(float).apply(
        lambda col: col.map(lambda value: _borrow_rate(float(value), config.borrow_tiers_annual) / config.periods_per_year)
    )
    return daily_rates.fillna(0.0)


def _spread_bps(adv: float, tiers: tuple[tuple[float, float], ...]) -> float:
    for threshold, spread in sorted(tiers, key=lambda item: item[0], reverse=True):
        if adv >= threshold:
            return float(spread)
    return float(tiers[-1][1]) if tiers else 0.0


def _borrow_rate(adv: float, tiers: tuple[tuple[float, float], ...]) -> float:
    for threshold, rate in sorted(tiers, key=lambda item: item[0], reverse=True):
        if adv >= threshold:
            return float(rate)
    return float(tiers[-1][1]) if tiers else 0.0
