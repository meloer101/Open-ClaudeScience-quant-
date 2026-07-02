from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
import pandas as pd

from quantbench.engine.metrics import (
    annualized_return,
    annualized_sharpe,
    compute_drawdown,
    monotonicity_score,
    periods_per_year_from_timestamps,
)


@dataclass
class CrossSectionalBacktestResult:
    metrics: dict[str, float]
    returns: pd.Series
    equity_curve: pd.Series
    drawdown: pd.Series
    factor_panel: pd.DataFrame
    group_returns: pd.DataFrame
    ic_series: pd.Series
    turnover: pd.Series

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "metrics": self.metrics,
            "series": {
                "timestamp": [str(item) for item in self.returns.index],
                "long_short_returns": self.returns.fillna(0).round(10).tolist(),
                "equity_curve": self.equity_curve.round(10).tolist(),
                "drawdown": self.drawdown.round(10).tolist(),
                "turnover": self.turnover.reindex(self.returns.index).fillna(0).round(6).tolist(),
                "ic": self.ic_series.reindex(self.returns.index).fillna(0).round(6).tolist(),
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
) -> CrossSectionalBacktestResult:
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
                    "forward_return": symbol_df["close"].pct_change().shift(-1),
                }
            )
        )

    factor_panel = pd.concat(factor_frames, ignore_index=True)
    factor_panel = factor_panel.replace([np.inf, -np.inf], np.nan).dropna(subset=["factor", "forward_return"])
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
    weights = _portfolio_weights(weighted, n_groups)
    turnover = weights.diff().abs().sum(axis=1).div(2).fillna(weights.abs().sum(axis=1))
    net_returns = long_short - turnover.reindex(long_short.index).fillna(0) * cost_bps / 10000

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
        "symbols": int(data["symbol"].nunique()),
        "observations": int(len(factor_panel)),
    }

    return CrossSectionalBacktestResult(
        metrics=metrics,
        returns=net_returns,
        equity_curve=equity_curve,
        drawdown=drawdown,
        factor_panel=factor_panel,
        group_returns=group_returns,
        ic_series=ic_series,
        turnover=turnover,
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


