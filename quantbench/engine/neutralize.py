from __future__ import annotations

import numpy as np
import pandas as pd


def rolling_betas(
    factor_panel: pd.DataFrame,
    *,
    window: int = 60,
    min_periods: int = 20,
) -> pd.Series:
    """Rolling beta of each symbol's close returns against the equal-weight
    universe return, as a MultiIndex (timestamp, symbol) Series. The window
    ending at t only uses returns known by the close of t, so the estimate is
    as causal as the factor itself. The equal-weight universe mean is a proxy
    benchmark - neutralizing against it removes common-market exposure without
    requiring external benchmark data."""
    closes = (
        factor_panel.pivot_table(index="timestamp", columns="symbol", values="close", aggfunc="last")
        .sort_index()
        .astype(float)
    )
    returns = closes.pct_change()
    market = returns.mean(axis=1)
    covariance = returns.rolling(window, min_periods=min_periods).cov(market)
    variance = market.rolling(window, min_periods=min_periods).var()
    betas = covariance.div(variance.replace(0.0, np.nan), axis=0)
    return betas.stack()


def neutralize_factor(
    factor_panel: pd.DataFrame,
    *,
    dimensions: list[str],
    betas: pd.Series | None = None,
    log_size: pd.Series | None = None,
    sector: pd.Series | None = None,
) -> pd.DataFrame:
    if not dimensions or factor_panel.empty:
        out = factor_panel.copy()
        out["neutralized"] = False
        return out
    if "beta" in dimensions and betas is None:
        raise ValueError("beta neutralization requested but no betas were provided; compute them (e.g. rolling_betas) first")

    frames = []
    for timestamp, section in factor_panel.groupby("timestamp", sort=False):
        section = section.copy()
        section["timestamp"] = timestamp
        design = _design_matrix(section, dimensions=dimensions, betas=betas, log_size=log_size, sector=sector)
        y = section["factor"].astype(float).to_numpy()
        valid = np.isfinite(y) & np.isfinite(design).all(axis=1)
        if int(valid.sum()) <= design.shape[1]:
            section["neutralized"] = False
            frames.append(section)
            continue
        resid = y.copy()
        fitted = design[valid] @ np.linalg.lstsq(design[valid], y[valid], rcond=None)[0]
        resid[valid] = y[valid] - fitted
        section.loc[valid, "factor"] = resid[valid]
        section["neutralized"] = False
        section.loc[valid, "neutralized"] = True
        frames.append(section)
    return pd.concat(frames, ignore_index=True) if frames else factor_panel.assign(neutralized=False)


def _map_symbol_series(section: pd.DataFrame, series: pd.Series) -> np.ndarray:
    symbols = section["symbol"].astype(str)
    if isinstance(series.index, pd.MultiIndex):
        keys = list(zip(section["timestamp"], symbols))
        return np.asarray([series.get(key, np.nan) for key in keys], dtype=float)
    return symbols.map(series).astype(float).to_numpy()


def _design_matrix(
    section: pd.DataFrame,
    *,
    dimensions: list[str],
    betas: pd.Series | None,
    log_size: pd.Series | None,
    sector: pd.Series | None,
) -> np.ndarray:
    symbols = section["symbol"].astype(str)
    columns = [np.ones(len(section), dtype=float)]
    if "beta" in dimensions and betas is not None:
        columns.append(_map_symbol_series(section, betas))
    if "size" in dimensions and log_size is not None:
        columns.append(_map_symbol_series(section, log_size))
    if "sector" in dimensions and sector is not None:
        sector_values = symbols.map(sector).fillna("unknown").astype(str)
        dummies = pd.get_dummies(sector_values, drop_first=True, dtype=float)
        for col in dummies.columns:
            columns.append(dummies[col].to_numpy(dtype=float))
    return np.column_stack(columns)
