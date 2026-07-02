from dataclasses import dataclass
from typing import Any

import pandas as pd

from quantbench.engine.metrics import (
    annualized_return,
    annualized_sharpe,
    compute_drawdown,
    information_coefficient,
    periods_per_year_from_timestamps,
)


@dataclass
class BacktestResult:
    metrics: dict[str, float]
    returns: pd.Series
    equity_curve: pd.Series
    drawdown: pd.Series
    position: pd.Series
    turnover: pd.Series

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "metrics": self.metrics,
            "series": {
                "timestamp": [str(item) for item in self.returns.index],
                "returns": self.returns.fillna(0).round(10).tolist(),
                "equity_curve": self.equity_curve.round(10).tolist(),
                "drawdown": self.drawdown.round(10).tolist(),
                "position": self.position.fillna(0).round(6).tolist(),
                "turnover": self.turnover.reindex(self.returns.index).fillna(0).round(6).tolist(),
            },
        }


def run_vectorized_backtest(price_df: pd.DataFrame, signal: pd.Series, cost_bps: float) -> BacktestResult:
    df = price_df.reset_index(drop=True).copy()
    signal = signal.reset_index(drop=True)
    timestamps = pd.to_datetime(df["timestamp"], utc=True)
    ppy = periods_per_year_from_timestamps(timestamps)

    forward_returns = df["close"].pct_change().shift(-1)
    position = _derive_position(signal)
    # position[t] is already causal (derived only from data known by close of bar t),
    # and forward_returns[t] already represents the t->t+1 return, so no additional
    # shift is needed here. Shifting position by another bar would silently misattribute
    # each return to a stale position one bar late (verified: it can flip the sign of
    # the return realized at a signal transition).
    gross_returns = position.fillna(0) * forward_returns.fillna(0)
    turnover = position.diff().abs().fillna(position.abs())
    net_returns = gross_returns - turnover * cost_bps / 10000
    net_returns.index = timestamps
    position.index = timestamps
    turnover.index = timestamps

    equity_curve = (1 + net_returns.fillna(0)).cumprod()
    drawdown = compute_drawdown(equity_curve)
    metrics = {
        "sharpe": round(annualized_sharpe(net_returns, ppy), 6),
        "annual_return": round(annualized_return(net_returns, ppy), 6),
        "max_drawdown": round(float(drawdown.min()), 6),
        "turnover_annual": round(float(turnover.mean() * ppy), 6),
        "ic_mean": round(information_coefficient(signal, forward_returns), 6),
    }
    return BacktestResult(
        metrics=metrics,
        returns=net_returns,
        equity_curve=equity_curve,
        drawdown=drawdown,
        position=position,
        turnover=turnover,
    )


def _derive_position(signal: pd.Series) -> pd.Series:
    clean = signal.astype(float)
    expanding_low = clean.expanding(min_periods=20).quantile(0.3)
    expanding_high = clean.expanding(min_periods=20).quantile(0.7)
    position = pd.Series(0.0, index=clean.index)
    position[clean <= expanding_low] = 1.0
    position[clean >= expanding_high] = -1.0
    return position.ffill().fillna(0.0)
