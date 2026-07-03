from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import linkage
from scipy.optimize import minimize
from scipy.spatial.distance import squareform

# Ordered roughly least -> most willing to estimate expected returns:
# equal_weight/inverse_variance/min_variance/risk_parity/hrp
# never touch the sample mean at all; only max_sharpe does, which is exactly why
# it is the one method this project treats as a cautionary comparison rather
# than the default (Michaud 1989 calls mean-variance optimization an "error
# maximizer" - the input it is most sensitive to, expected returns, is also
# the input estimated least reliably from a short return history).
PORTFOLIO_METHODS = ("equal_weight", "inverse_variance", "min_variance", "risk_parity", "max_sharpe", "hrp")


@dataclass(frozen=True)
class OptimizationResult:
    method: str
    weights: dict[str, float]
    diagnostics: dict[str, Any]


def ledoit_wolf_covariance(returns: pd.DataFrame) -> tuple[np.ndarray, float]:
    """Ledoit-Wolf (2003) shrinkage of the sample covariance toward a
    constant-correlation target. Implemented directly rather than pulling in
    scikit-learn, since numpy/scipy already cover every other numeric
    dependency in this project.

    With only a handful of candidate factors (<= PORTFOLIO_MAX_FACTORS) the
    sample covariance isn't as catastrophically ill-conditioned as it would be
    for, say, 500 equities - but shrinkage is still the responsible default:
    it costs nothing when the sample matrix is already well-behaved (the
    estimated intensity comes out near zero) and materially stabilizes it
    when it isn't.
    """
    X = returns.to_numpy(dtype=float)
    T, N = X.shape
    if N < 2:
        var = float(np.var(X, ddof=0)) if T > 0 else 0.0
        return np.array([[max(var, 1e-12)]]), 0.0
    if T < 2:
        # Not enough observations to estimate anything beyond the target itself.
        var = np.var(X, axis=0, ddof=0)
        var = np.where(var <= 0, 1e-12, var)
        return np.diag(var), 1.0

    Xc = X - X.mean(axis=0, keepdims=True)
    sample = (Xc.T @ Xc) / T
    var = np.diag(sample).copy()
    var = np.where(var <= 0, 1e-12, var)
    std = np.sqrt(var)
    corr = sample / np.outer(std, std)
    np.fill_diagonal(corr, 1.0)
    off_diag_sum = corr.sum() - N
    avg_corr = off_diag_sum / (N * (N - 1)) if N > 1 else 0.0

    target = avg_corr * np.outer(std, std)
    np.fill_diagonal(target, var)

    # Shrinkage intensity estimate following Ledoit & Wolf (2003), "Improved
    # estimation of the covariance matrix of stock returns with an
    # application to portfolio selection" - pi_hat is the sum of asymptotic
    # variances of the sample covariance entries, rho_hat the corresponding
    # covariance with the constant-correlation target, and gamma_hat the
    # squared misspecification of the target itself.
    pi_mat = np.zeros((N, N))
    for i in range(N):
        for j in range(N):
            term = Xc[:, i] * Xc[:, j] - sample[i, j]
            pi_mat[i, j] = np.mean(term**2)
    pi_hat = pi_mat.sum()

    rho_hat = pi_mat.trace()
    for i in range(N):
        for j in range(N):
            if i == j:
                continue
            theta_ii_ij = np.mean((Xc[:, i] ** 2 - sample[i, i]) * (Xc[:, i] * Xc[:, j] - sample[i, j]))
            theta_jj_ij = np.mean((Xc[:, j] ** 2 - sample[j, j]) * (Xc[:, i] * Xc[:, j] - sample[i, j]))
            rho_hat += (avg_corr / 2) * (std[j] / std[i] * theta_ii_ij + std[i] / std[j] * theta_jj_ij)

    gamma_hat = float(np.sum((target - sample) ** 2))
    if gamma_hat <= 1e-18:
        delta = 0.0
    else:
        kappa_hat = (pi_hat - rho_hat) / gamma_hat
        delta = max(0.0, min(1.0, kappa_hat / T))

    shrunk = delta * target + (1 - delta) * sample
    return shrunk, float(delta)


def optimize(
    returns: pd.DataFrame,
    method: str,
    *,
    max_weight: float = 1.0,
    cov: np.ndarray | None = None,
) -> OptimizationResult:
    if method not in PORTFOLIO_METHODS:
        raise ValueError(f"unknown portfolio method: {method!r}, expected one of {PORTFOLIO_METHODS}")
    if returns.empty:
        raise ValueError("returns is empty")

    names = list(returns.columns)
    n = len(names)
    if n == 1:
        return OptimizationResult(method=method, weights={names[0]: 1.0}, diagnostics={"degenerate": "single_factor"})

    max_weight = _effective_max_weight(n, max_weight)
    shrinkage: float | None = None
    if cov is None:
        cov, shrinkage = ledoit_wolf_covariance(returns)

    if method == "equal_weight":
        w = np.full(n, 1.0 / n)
        diagnostics: dict[str, Any] = {}
    elif method == "inverse_variance":
        var = np.diag(cov)
        var = np.where(var <= 0, 1e-12, var)
        inv = 1.0 / var
        w = inv / inv.sum()
        diagnostics = {}
    elif method == "min_variance":
        w, diagnostics = _min_variance_weights(cov, max_weight)
    elif method == "risk_parity":
        w, diagnostics = _risk_parity_weights(cov, max_weight)
    elif method == "max_sharpe":
        mu = returns.mean().to_numpy()
        w, diagnostics = _max_sharpe_weights(mu, cov, max_weight)
    else:  # hrp
        w, diagnostics = _hrp_weights(cov)

    if shrinkage is not None:
        diagnostics["shrinkage_intensity"] = round(shrinkage, 6)
    diagnostics["condition_number"] = float(np.linalg.cond(cov))
    diagnostics["max_weight"] = max_weight

    # min_variance/risk_parity/max_sharpe already respect max_weight via their
    # own SLSQP bounds, but equal_weight/inverse_variance/hrp are closed-form
    # and have no such constraint built in - without this, a single dominant
    # factor could receive far more than max_weight under those methods,
    # silently defeating the whole point of the cap (preventing "portfolio"
    # optimization from just picking one factor).
    w = _apply_max_weight_cap(w, max_weight)
    weights = {name: float(value) for name, value in zip(names, w)}
    return OptimizationResult(method=method, weights=weights, diagnostics=diagnostics)


def evaluate_all_methods(returns: pd.DataFrame, *, max_weight: float = 1.0) -> dict[str, OptimizationResult]:
    """All PORTFOLIO_METHODS evaluated against the same (single) shrunk
    covariance estimate, so the comparison table isn't confounded by each
    method re-estimating the covariance matrix slightly differently."""
    cov, shrinkage = ledoit_wolf_covariance(returns)
    results = {}
    for method in PORTFOLIO_METHODS:
        result = optimize(returns, method, max_weight=max_weight, cov=cov)
        result.diagnostics.setdefault("shrinkage_intensity", round(shrinkage, 6))
        results[method] = result
    return results


def _effective_max_weight(n: int, max_weight: float) -> float:
    # A cap tighter than 1/n makes the equal-weight constraint infeasible.
    return max(max_weight, 1.0 / n)


def _min_variance_weights(cov: np.ndarray, max_weight: float) -> tuple[np.ndarray, dict[str, Any]]:
    n = cov.shape[0]
    x0 = np.full(n, 1.0 / n)
    bounds = [(0.0, max_weight)] * n
    constraints = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
    result = minimize(
        lambda w: float(w @ cov @ w),
        x0,
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 500, "ftol": 1e-12},
    )
    w = _normalize(result.x if result.success else x0)
    return w, {"converged": bool(result.success), "iterations": int(result.nit)}


def _risk_parity_weights(cov: np.ndarray, max_weight: float) -> tuple[np.ndarray, dict[str, Any]]:
    n = cov.shape[0]
    x0 = np.full(n, 1.0 / n)
    bounds = [(1e-6, max_weight)] * n
    constraints = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]

    def objective(w: np.ndarray) -> float:
        port_var = float(w @ cov @ w)
        if port_var <= 0:
            return 0.0
        marginal = cov @ w
        rc = w * marginal
        total = rc.sum()
        if total <= 0:
            return 0.0
        rc_share = rc / total
        target = 1.0 / n
        return float(np.sum((rc_share - target) ** 2))

    result = minimize(
        objective, x0, method="SLSQP", bounds=bounds, constraints=constraints, options={"maxiter": 1000, "ftol": 1e-14}
    )
    w = _normalize(result.x if result.success else x0)
    return w, {"converged": bool(result.success), "iterations": int(result.nit), "objective": objective(w)}


def _max_sharpe_weights(mu: np.ndarray, cov: np.ndarray, max_weight: float) -> tuple[np.ndarray, dict[str, Any]]:
    n = len(mu)
    x0 = np.full(n, 1.0 / n)
    bounds = [(0.0, max_weight)] * n
    constraints = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]

    def neg_sharpe(w: np.ndarray) -> float:
        port_ret = float(w @ mu)
        port_vol = float(np.sqrt(max(w @ cov @ w, 1e-18)))
        return -port_ret / port_vol

    result = minimize(
        neg_sharpe, x0, method="SLSQP", bounds=bounds, constraints=constraints, options={"maxiter": 500, "ftol": 1e-12}
    )
    w = _normalize(result.x if result.success else x0)
    diagnostics: dict[str, Any] = {"converged": bool(result.success), "iterations": int(result.nit)}
    if np.all(mu <= 0):
        diagnostics["warning"] = (
            "all candidate factors have non-positive mean return over this window; max_sharpe allocation "
            "reflects the least-negative option(s), not a genuine edge"
        )
    return w, diagnostics


def _hrp_weights(cov: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    """Hierarchical Risk Parity (Lopez de Prado 2016): cluster factors by
    correlation distance, order them by the dendrogram (quasi-diagonalization),
    then recursively split risk budget top-down by inverse-variance cluster
    weight. Never inverts the covariance matrix, unlike min-variance/max-Sharpe,
    which makes it the most numerically robust method here when factors are
    highly correlated (the condition where naive inversion is worst-behaved)."""
    n = cov.shape[0]
    if n == 2:
        # linkage() needs >= 3 observations for a condensed distance vector;
        # for exactly two factors HRP's own bisection degenerates to the same
        # inverse-cluster-variance split it would produce anyway.
        sort_ix = [0, 1]
    else:
        corr = _cov_to_corr(cov)
        dist = np.sqrt(np.clip((1 - corr) / 2, 0, None))
        condensed = squareform(dist, checks=False)
        link = linkage(condensed, method="single")
        sort_ix = _quasi_diagonal_order(link, n)

    weights = _recursive_bisection(cov, sort_ix)
    return _normalize(weights), {"cluster_order": sort_ix}


def _quasi_diagonal_order(link: np.ndarray, n_leaves: int) -> list[int]:
    """Sorts leaves so that highly-correlated items end up adjacent, following
    Lopez de Prado's reference implementation (Advances in Financial Machine
    Learning, ch. 16)."""
    link = link.astype(int)
    sort_ix = pd.Series([link[-1, 0], link[-1, 1]])
    while sort_ix.max() >= n_leaves:
        sort_ix.index = range(0, sort_ix.shape[0] * 2, 2)
        expandable = sort_ix[sort_ix >= n_leaves]
        positions = expandable.index
        cluster_rows = expandable.to_numpy() - n_leaves
        sort_ix[positions] = link[cluster_rows, 0]
        new_items = pd.Series(link[cluster_rows, 1], index=positions + 1)
        sort_ix = pd.concat([sort_ix, new_items]).sort_index()
        sort_ix.index = range(sort_ix.shape[0])
    return sort_ix.tolist()


def _cluster_variance(cov: np.ndarray, items: list[int]) -> float:
    sub_cov = cov[np.ix_(items, items)]
    diag = np.diag(sub_cov)
    diag = np.where(diag <= 0, 1e-12, diag)
    ivp = 1.0 / diag
    ivp = ivp / ivp.sum()
    return float(ivp @ sub_cov @ ivp)


def _recursive_bisection(cov: np.ndarray, sort_ix: list[int]) -> np.ndarray:
    n = len(sort_ix)
    weights = np.ones(n)
    position_of = {item: pos for pos, item in enumerate(sort_ix)}

    def _bisect(items: list[int]) -> None:
        if len(items) <= 1:
            return
        mid = len(items) // 2
        left, right = items[:mid], items[mid:]
        var_left = _cluster_variance(cov, left)
        var_right = _cluster_variance(cov, right)
        denom = var_left + var_right
        alpha = 1.0 - var_left / denom if denom > 0 else 0.5
        for item in left:
            weights[position_of[item]] *= alpha
        for item in right:
            weights[position_of[item]] *= 1.0 - alpha
        _bisect(left)
        _bisect(right)

    _bisect(sort_ix)
    result = np.zeros(n)
    for pos, item in enumerate(sort_ix):
        result[item] = weights[pos]
    return result


def _cov_to_corr(cov: np.ndarray) -> np.ndarray:
    std = np.sqrt(np.diag(cov))
    std = np.where(std <= 0, 1e-12, std)
    corr = cov / np.outer(std, std)
    np.fill_diagonal(corr, 1.0)
    return np.clip(corr, -1.0, 1.0)


def _normalize(w: np.ndarray) -> np.ndarray:
    w = np.clip(w, 0, None)
    total = w.sum()
    return w / total if total > 0 else np.full(len(w), 1.0 / len(w))


def _apply_max_weight_cap(w: np.ndarray, max_weight: float) -> np.ndarray:
    """Water-filling cap: pin any weight above max_weight to the cap, then
    redistribute the freed-up budget proportionally among the still-uncapped
    weights, repeating until nothing exceeds the cap. Caller is expected to
    have already relaxed max_weight to >= 1/n (_effective_max_weight), so this
    always terminates - each pass caps at least one more weight or stops."""
    w = _normalize(w)
    n = len(w)
    if max_weight >= 1.0 or n == 0:
        return w
    capped = np.zeros(n, dtype=bool)
    for _ in range(n):
        over = (w > max_weight + 1e-12) & ~capped
        if not over.any():
            break
        w[over] = max_weight
        capped[over] = True
        free = ~capped
        remaining_budget = 1.0 - max_weight * capped.sum()
        remaining_sum = w[free].sum()
        if free.any():
            if remaining_sum > 0 and remaining_budget > 0:
                w[free] *= remaining_budget / remaining_sum
            else:
                w[free] = max(remaining_budget, 0.0) / free.sum()
    return _normalize(w)
