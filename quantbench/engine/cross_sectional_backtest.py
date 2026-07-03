from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
import pandas as pd

from quantbench.review.bootstrap import metrics_ci
from quantbench.engine.costs import LiquidityCostConfig, apply_liquidity_costs, capacity_curve
from quantbench.engine.execution import ExecutionConfig, forward_returns_for_execution
from quantbench.engine.metrics import (
    annualized_return,
    annualized_sharpe,
    compute_drawdown,
    ICSignificance,
    ic_newey_west,
    monotonicity_score,
    periods_per_year_from_timestamps,
)
from quantbench.engine.neutralize import neutralize_factor, rolling_betas


@dataclass
class CrossSectionalBacktestResult:
    metrics: dict[str, float]
    returns: pd.Series
    equity_curve: pd.Series
    drawdown: pd.Series
    factor_panel: pd.DataFrame
    group_returns: pd.DataFrame
    ic_series: pd.Series
    ic_significance: ICSignificance
    turnover: pd.Series
    execution: ExecutionConfig
    long_short_contribution: dict[str, float]
    capacity_curve: list[dict[str, float]]
    liquidity_cost: pd.Series
    borrow_cost: pd.Series

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "metrics": self.metrics,
            "metrics_ci": metrics_ci(self.returns),
            "ic_significance": self.ic_significance.to_dict(),
            "execution": self.execution.to_dict(),
            "long_short_contribution": self.long_short_contribution,
            "capacity_curve": self.capacity_curve,
            "series": {
                "timestamp": [str(item) for item in self.returns.index],
                "long_short_returns": self.returns.fillna(0).round(10).tolist(),
                "equity_curve": self.equity_curve.round(10).tolist(),
                "drawdown": self.drawdown.round(10).tolist(),
                "turnover": self.turnover.reindex(self.returns.index).fillna(0).round(6).tolist(),
                "ic": self.ic_series.reindex(self.returns.index).fillna(0).round(6).tolist(),
                "liquidity_cost": self.liquidity_cost.reindex(self.returns.index).fillna(0).round(10).tolist(),
                "borrow_cost": self.borrow_cost.reindex(self.returns.index).fillna(0).round(10).tolist(),
            },
            "group_returns": {
                str(col): self.group_returns[col].fillna(0).round(10).tolist() for col in self.group_returns.columns
            },
        }


def run_cross_sectional_backtest(
    panel: pd.DataFrame,
    compute_factor: Callable[[pd.DataFrame], pd.Series],
    n_groups: int = 10,
    cost_bps: float = 5.0,
    rebalance: str = "1D",
    membership_intervals: dict[str, list[tuple[str, str]] | list[list[str]]] | None = None,
    funding_rates: pd.DataFrame | None = None,
    execution: ExecutionConfig | None = None,
    liquidity_cost_config: LiquidityCostConfig | None = None,
    borrow_rates: pd.DataFrame | None = None,
    neutralize: list[str] | None = None,
    sector: pd.Series | None = None,
) -> CrossSectionalBacktestResult:
    execution = execution or ExecutionConfig()
    if n_groups < 2:
        raise ValueError("n_groups must be at least 2")
    if panel.empty:
        raise ValueError("panel is empty")

    data = panel.copy()
    data["timestamp"] = pd.to_datetime(data["timestamp"], utc=True)
    data = data.sort_values(["symbol", "timestamp"]).reset_index(drop=True)

    # Found via a real crypto universe run: when fewer symbols have data than
    # n_groups requires, _assign_groups (below) marks every timestamp's group
    # as NaN - not just some - because `len(section) < n_groups` is true for
    # every section. That silently degrades into an empty weighted panel and
    # a "0.0 Sharpe / NaN drawdown" result that looks like a (bad) real
    # backtest instead of a n_groups/universe-size mismatch, and in some data
    # shapes surfaces as an opaque numpy TypeError three layers downstream
    # instead. A clear, immediate error here is far more actionable - callers
    # (including the LLM Coordinator, which otherwise burns retries rewriting
    # compute() when the real problem is n_groups vs. universe size) can
    # reduce n_groups or fetch a larger universe, rather than debugging a
    # unicorn "isfinite" exception that has nothing to do with their code.
    available_symbols = data["symbol"].nunique()
    if available_symbols < n_groups:
        raise ValueError(
            f"n_groups={n_groups} requires at least {n_groups} symbols with data, but only "
            f"{available_symbols} symbol(s) have any data in this panel. Reduce n_groups to at "
            f"most {available_symbols}, or use a universe with more symbols that have data over "
            "this date range."
        )

    factor_frames = []
    for symbol, symbol_df in data.groupby("symbol", sort=False):
        symbol_df = symbol_df.sort_values("timestamp").reset_index(drop=True)
        factor = compute_factor(symbol_df)
        factor = pd.Series(factor, index=symbol_df.index, dtype="float64")
        factor_frames.append(
            pd.DataFrame(
                {
                    "timestamp": symbol_df["timestamp"],
                    "symbol": symbol,
                    "factor": factor,
                    "forward_return": forward_returns_for_execution(symbol_df, execution),
                    "close": symbol_df["close"],
                    "open": symbol_df["open"] if "open" in symbol_df.columns else np.nan,
                    "volume": symbol_df["volume"] if "volume" in symbol_df.columns else np.nan,
                    "dollar_volume": symbol_df["close"] * symbol_df["volume"] if "volume" in symbol_df.columns else np.nan,
                }
            )
        )

    factor_panel = pd.concat(factor_frames, ignore_index=True)
    factor_panel = factor_panel.replace([np.inf, -np.inf], np.nan).dropna(subset=["factor", "forward_return"])
    factor_panel = _apply_membership_mask(factor_panel, membership_intervals)
    available_factor_symbols = factor_panel["symbol"].nunique()
    if available_factor_symbols < n_groups:
        raise ValueError(
            f"n_groups={n_groups} requires at least {n_groups} symbols with factor observations inside "
            f"the requested universe membership intervals, but only {available_factor_symbols} symbol(s) "
            "remain. Reduce n_groups or use a wider/date-compatible universe."
        )
    if neutralize:
        size_proxy = (
            np.log(factor_panel.set_index(["timestamp", "symbol"])["dollar_volume"].replace(0, np.nan))
            if "size" in neutralize and "dollar_volume" in factor_panel.columns
            else None
        )
        betas = rolling_betas(factor_panel) if "beta" in neutralize else None
        factor_panel = neutralize_factor(
            factor_panel, dimensions=neutralize, betas=betas, log_size=size_proxy, sector=sector
        )
    factor_panel = _assign_groups(factor_panel, n_groups)

    weighted = factor_panel.dropna(subset=["group"]).copy()
    weighted["group"] = weighted["group"].astype(int)
    group_returns = (
        weighted.groupby(["timestamp", "group"], observed=True)["forward_return"]
        .mean()
        .unstack("group")
        .sort_index()
    )
    group_returns = group_returns.reindex(columns=range(1, n_groups + 1))

    long_short = group_returns[n_groups].fillna(0) - group_returns[1].fillna(0)
    target_long_short = long_short.copy()
    weights = _portfolio_weights(weighted, n_groups)
    turnover = weights.diff().abs().sum(axis=1).div(2).fillna(weights.abs().sum(axis=1))
    funding_cost = _funding_cost(weights, funding_rates).reindex(long_short.index).fillna(0)
    borrow_cost = _borrow_cost(weights, borrow_rates).reindex(long_short.index).fillna(0)
    liquidity_cost = pd.Series(0.0, index=long_short.index)
    curve: list[dict[str, float]] = []
    if liquidity_cost_config is not None and not weights.empty and "dollar_volume" in weighted.columns:
        dollar_volume = (
            weighted.pivot_table(index="timestamp", columns="symbol", values="dollar_volume", aggfunc="last")
            .reindex(index=weights.index, columns=weights.columns)
            .sort_index()
        )
        actual_weights, liquidity_cost = apply_liquidity_costs(weights, dollar_volume, liquidity_cost_config)
        symbol_returns = (
            weighted.pivot_table(index="timestamp", columns="symbol", values="forward_return", aggfunc="last")
            .reindex(index=weights.index, columns=weights.columns, fill_value=0)
        )
        long_short = (actual_weights * symbol_returns).sum(axis=1).reindex(long_short.index).fillna(0)
        turnover = actual_weights.diff().abs().sum(axis=1).div(2).fillna(actual_weights.abs().sum(axis=1))
        curve = capacity_curve(target_long_short, weights, dollar_volume, liquidity_cost_config)
        variable_cost = liquidity_cost.reindex(long_short.index).fillna(0)
    else:
        variable_cost = turnover.reindex(long_short.index).fillna(0) * cost_bps / 10000
    gross_after_carry = long_short - funding_cost - borrow_cost
    net_returns = gross_after_carry - variable_cost

    equity_curve = (1 + net_returns.fillna(0)).cumprod()
    drawdown = compute_drawdown(equity_curve)
    ic_series = _cross_sectional_ic(factor_panel, method="spearman")
    pearson_ic_series = _cross_sectional_ic(factor_panel, method="pearson")
    ppy = periods_per_year_from_timestamps(net_returns.index)
    avg_group_returns = group_returns.mean()

    metrics = {
        "sharpe": round(annualized_sharpe(net_returns, ppy), 6),
        "annual_return": round(annualized_return(net_returns, ppy), 6),
        "max_drawdown": round(float(drawdown.min()), 6),
        "turnover_annual": round(float(turnover.mean() * ppy), 6),
        "ic_mean": round(float(pearson_ic_series.mean()) if not pearson_ic_series.empty else 0.0, 6),
        "rank_ic_mean": round(float(ic_series.mean()) if not ic_series.empty else 0.0, 6),
        "monotonicity_score": round(monotonicity_score(avg_group_returns), 6),
        "symbols": int(factor_panel["symbol"].nunique()),
        "observations": int(len(factor_panel)),
        "funding_cost_total": round(float(funding_cost.sum()), 6),
        "borrow_cost_total": round(float(borrow_cost.sum()), 6),
        "liquidity_cost_total": round(float(liquidity_cost.sum()), 6),
        "sharpe_before_funding": round(annualized_sharpe(long_short, ppy), 6),
    }

    return CrossSectionalBacktestResult(
        metrics=metrics,
        returns=net_returns,
        equity_curve=equity_curve,
        drawdown=drawdown,
        factor_panel=factor_panel,
        group_returns=group_returns,
        ic_series=ic_series,
        ic_significance=ic_newey_west(ic_series),
        turnover=turnover,
        execution=execution,
        long_short_contribution=_long_short_contribution(group_returns, n_groups),
        capacity_curve=curve,
        liquidity_cost=liquidity_cost.reindex(net_returns.index).fillna(0),
        borrow_cost=borrow_cost.reindex(net_returns.index).fillna(0),
    )


def _assign_groups(factor_panel: pd.DataFrame, n_groups: int) -> pd.DataFrame:
    frames = []
    for timestamp, section in factor_panel.groupby("timestamp", sort=False):
        section = section.copy()
        section["timestamp"] = timestamp
        if section["factor"].nunique(dropna=True) < n_groups or len(section) < n_groups:
            section["group"] = np.nan
        else:
            ranked = section["factor"].rank(method="first")
            section["group"] = pd.qcut(ranked, q=n_groups, labels=range(1, n_groups + 1), duplicates="drop")
        frames.append(section)
    return pd.concat(frames, ignore_index=True) if frames else factor_panel.assign(group=np.nan)


def _apply_membership_mask(
    factor_panel: pd.DataFrame,
    membership_intervals: dict[str, list[tuple[str, str]] | list[list[str]]] | None,
) -> pd.DataFrame:
    if not membership_intervals:
        return factor_panel
    if factor_panel.empty:
        return factor_panel

    timestamps = pd.to_datetime(factor_panel["timestamp"], utc=True)
    mask = pd.Series(False, index=factor_panel.index)
    symbols = factor_panel["symbol"].astype(str)
    for symbol, intervals in membership_intervals.items():
        symbol_mask = symbols.eq(str(symbol))
        if not symbol_mask.any():
            continue
        active = pd.Series(False, index=factor_panel.index)
        for start, end in intervals:
            start_ts = pd.to_datetime(start, utc=True)
            end_ts = pd.to_datetime(end, utc=True)
            active |= (timestamps >= start_ts) & (timestamps <= end_ts)
        mask |= symbol_mask & active
    return factor_panel.loc[mask].reset_index(drop=True)


def _portfolio_weights(weighted: pd.DataFrame, n_groups: int) -> pd.DataFrame:
    long_leg = weighted[weighted["group"] == n_groups]
    short_leg = weighted[weighted["group"] == 1]
    rows = []
    for timestamp, leg in long_leg.groupby("timestamp"):
        symbols = leg["symbol"].tolist()
        if symbols:
            rows.extend({"timestamp": timestamp, "symbol": symbol, "weight": 1 / len(symbols)} for symbol in symbols)
    for timestamp, leg in short_leg.groupby("timestamp"):
        symbols = leg["symbol"].tolist()
        if symbols:
            rows.extend({"timestamp": timestamp, "symbol": symbol, "weight": -1 / len(symbols)} for symbol in symbols)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).pivot_table(index="timestamp", columns="symbol", values="weight", fill_value=0).sort_index()


def _funding_cost(weights: pd.DataFrame, funding_rates: pd.DataFrame | None) -> pd.Series:
    if weights.empty or funding_rates is None or funding_rates.empty:
        return pd.Series(0.0, index=weights.index)
    required = {"timestamp", "symbol", "funding_rate"}
    if not required.issubset(funding_rates.columns):
        raise ValueError("funding_rates must contain timestamp, symbol, and funding_rate columns")
    rates = funding_rates.loc[:, ["timestamp", "symbol", "funding_rate"]].copy()
    rates["timestamp"] = pd.to_datetime(rates["timestamp"], utc=True)
    rates["funding_rate"] = pd.to_numeric(rates["funding_rate"], errors="coerce")
    rate_matrix = (
        rates.dropna(subset=["funding_rate"])
        .pivot_table(index="timestamp", columns="symbol", values="funding_rate", aggfunc="sum", fill_value=0)
        .reindex(index=weights.index, columns=weights.columns, fill_value=0)
    )
    return (weights * rate_matrix).sum(axis=1)


def _borrow_cost(weights: pd.DataFrame, borrow_rates: pd.DataFrame | None) -> pd.Series:
    if weights.empty or borrow_rates is None or borrow_rates.empty:
        return pd.Series(0.0, index=weights.index)
    if {"timestamp", "symbol", "borrow_rate"}.issubset(borrow_rates.columns):
        rates = borrow_rates.loc[:, ["timestamp", "symbol", "borrow_rate"]].copy()
        rates["timestamp"] = pd.to_datetime(rates["timestamp"], utc=True)
        rates["borrow_rate"] = pd.to_numeric(rates["borrow_rate"], errors="coerce")
        rate_matrix = (
            rates.dropna(subset=["borrow_rate"])
            .pivot_table(index="timestamp", columns="symbol", values="borrow_rate", aggfunc="sum", fill_value=0)
            .reindex(index=weights.index, columns=weights.columns, fill_value=0)
        )
    else:
        rate_matrix = borrow_rates.reindex(index=weights.index, columns=weights.columns, fill_value=0)
    return (weights.clip(upper=0).abs() * rate_matrix).sum(axis=1)


def _long_short_contribution(group_returns: pd.DataFrame, n_groups: int) -> dict[str, float]:
    long_contribution = float(group_returns[n_groups].fillna(0).sum()) if n_groups in group_returns else 0.0
    short_contribution = float((-group_returns[1].fillna(0)).sum()) if 1 in group_returns else 0.0
    total_abs = abs(long_contribution) + abs(short_contribution)
    short_share = 0.0 if total_abs == 0 else abs(short_contribution) / total_abs
    return {
        "long_contribution": round(long_contribution, 6),
        "short_contribution": round(short_contribution, 6),
        "short_share": round(short_share, 6),
    }


def _cross_sectional_ic(factor_panel: pd.DataFrame, method: str) -> pd.Series:
    values = {}
    for timestamp, section in factor_panel.groupby("timestamp"):
        clean = section[["factor", "forward_return"]].dropna()
        if len(clean) < 3 or clean["factor"].nunique() < 2 or clean["forward_return"].nunique() < 2:
            values[timestamp] = 0.0
            continue
        corr = clean["factor"].corr(clean["forward_return"], method=method)
        values[timestamp] = 0.0 if pd.isna(corr) else float(corr)
    return pd.Series(values).sort_index()
