from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable

import pandas as pd

from quantbench.review.beta_exposure import compute_beta
from quantbench.review.cost_sensitivity import CostSensitivityResult, run_cost_sensitivity_check
from quantbench.review.cpcv import run_cpcv
from quantbench.review.deflated_sharpe import MIN_DSR_OBSERVATIONS, deflated_sharpe_ratio
from quantbench.review.lookback import estimate_lookback_bars
from quantbench.review.lookahead import LookaheadIssue, detect_lookahead
from quantbench.review.out_of_sample import OOSResult, run_out_of_sample_check
from quantbench.review.pbo import PBOResult
from quantbench.review.parameter_stability import ParameterStabilityResult, run_parameter_stability_check
from quantbench.review.regime import yearly_return_contribution
from quantbench.review.symbol_concentration import symbol_concentration_from_factor_panel
from quantbench.review.tail_dependence import MAX_BEST_DAYS, best_days_contribution_share
from quantbench.review.walk_forward import WalkForwardResult, run_walk_forward
from quantbench.engine.metrics import ICSignificance, ic_newey_west, periods_per_year_from_timestamps


SEVERITY_ORDER = ("critical", "warning", "info", "pass")
PARAMETER_INSTABILITY_THRESHOLD = 1.0
REGIME_CONCENTRATION_THRESHOLD = 0.7
TAIL_DEPENDENCE_SHARE_WARNING = 0.35
TURNOVER_ANNUAL_WARNING = 1000.0
BETA_R2_WARNING = 0.5
BETA_ABS_WARNING = 0.7
MIN_OOS_OBSERVATIONS = 30
MIN_BETA_OBSERVATIONS = 30
MIN_WALK_FORWARD_WINDOWS = 3
MIN_CPCV_PATHS = 3
UNIVERSE_COVERAGE_MISSING_WARNING = 0.10
UNIVERSE_COVERAGE_MISSING_CRITICAL = 0.40


@dataclass(frozen=True)
class ReviewFinding:
    check: str
    severity: str
    message: str
    detail: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReviewReport:
    findings: list[ReviewFinding]
    verdict: str
    verdict_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "verdict_reason": self.verdict_reason,
            "findings": [finding.to_dict() for finding in self.findings],
        }

    def to_markdown(self) -> str:
        groups = {
            "critical": "### CRITICAL ISSUES",
            "warning": "### WARNINGS",
            "info": "### INFO / SKIPPED",
            "pass": "### PASSED",
        }
        blocks: list[str] = []
        for severity in SEVERITY_ORDER:
            items = [finding for finding in self.findings if finding.severity == severity]
            if not items:
                continue
            lines = [groups[severity]]
            lines.extend(f"- **{finding.check}**: {finding.message}" for finding in items)
            blocks.append("\n".join(lines))
        blocks.append(f"### VERDICT\n**{self.verdict}** - {self.verdict_reason}")
        return "\n\n".join(blocks)


def determine_verdict(findings: list[ReviewFinding]) -> tuple[str, str]:
    critical = [finding for finding in findings if finding.severity == "critical"]
    warnings = [finding for finding in findings if finding.severity == "warning"]
    if critical:
        return "REJECTED", f"{len(critical)} critical finding(s): " + "; ".join(f.message for f in critical[:3])
    if len(warnings) >= 3:
        return "WEAK", f"{len(warnings)} warning finding(s) indicate weak robustness."
    if warnings:
        return "PROMISING", f"{len(warnings)} warning finding(s); result needs follow-up."
    return "STRONG", "No critical or warning findings from deterministic reviewer checks."


def run_review(
    *,
    code: str,
    returns: pd.Series,
    cost_bps: float,
    rerun_at_cost: Callable[[float], dict[str, float]],
    rerun_with_code: Callable[[str], dict[str, float] | None],
    out_of_sample_data: pd.DataFrame,
    run_on_data: Callable[[pd.DataFrame], dict[str, float]],
    benchmark_returns: pd.Series | None = None,
    benchmark_symbol: str | None = None,
    factor_panel: pd.DataFrame | None = None,
    n_groups: int | None = None,
    turnover_annual: float | None = None,
    n_trials: int = 1,
    trial_sharpes: list[float] | None = None,
    pbo_result: PBOResult | None = None,
    universe_coverage: dict[str, Any] | None = None,
    funding_cost_sensitivity: dict[str, Any] | None = None,
    ic_series: pd.Series | None = None,
    ic_significance: ICSignificance | dict[str, Any] | None = None,
) -> ReviewReport:
    findings: list[ReviewFinding] = []
    findings.extend(_safe("lookahead", lambda: _lookahead_findings(code)))
    findings.extend(_safe("out_of_sample", lambda: [_oos_finding(run_out_of_sample_check(out_of_sample_data, run_on_data))]))
    findings.extend(_safe("cost_sensitivity", lambda: [_cost_finding(run_cost_sensitivity_check(cost_bps, rerun_at_cost))]))
    findings.extend(_safe("parameter_stability", lambda: [_parameter_finding(run_parameter_stability_check(code, rerun_with_code))]))
    findings.extend(_safe("deflated_sharpe", lambda: [_dsr_finding(returns, n_trials, trial_sharpes)]))
    findings.extend(_safe("walk_forward", lambda: [_walk_forward_finding(run_walk_forward(returns))]))
    findings.extend(_safe("cpcv", lambda: [_cpcv_finding(code, returns)]))
    findings.extend(_safe("ic_significance", lambda: [_ic_significance_finding(ic_series, ic_significance)]))
    if pbo_result is not None:
        findings.append(_pbo_finding(pbo_result))
    findings.extend(_safe("regime", lambda: [_regime_finding(returns)]))
    findings.extend(_safe("tail_dependence", lambda: [_tail_finding(returns)]))
    findings.append(_turnover_finding(turnover_annual))
    findings.extend(_safe("beta_exposure", lambda: [_beta_finding(returns, benchmark_returns, benchmark_symbol)]))
    if factor_panel is not None and n_groups is not None:
        findings.extend(_safe("symbol_concentration", lambda: [_symbol_finding(factor_panel, n_groups)]))
    if universe_coverage is not None:
        findings.append(_universe_coverage_finding(universe_coverage))
    if funding_cost_sensitivity is not None:
        findings.append(_funding_cost_finding(funding_cost_sensitivity))
    verdict, reason = determine_verdict(findings)
    return ReviewReport(findings=findings, verdict=verdict, verdict_reason=reason)


def _safe(check: str, fn: Callable[[], list[ReviewFinding]]) -> list[ReviewFinding]:
    try:
        return fn()
    except Exception as exc:
        return [
            ReviewFinding(
                check=check,
                severity="info",
                message=f"Check skipped because it failed internally: {type(exc).__name__}: {exc}",
                detail={},
            )
        ]


def _lookahead_findings(code: str) -> list[ReviewFinding]:
    issues = detect_lookahead(code)
    if not issues:
        return [ReviewFinding("lookahead", "pass", "No known lookahead patterns detected.", {})]
    findings: list[ReviewFinding] = []
    for issue in issues:
        severity = "warning" if issue.pattern == "unwindowed_full_column_aggregate" else "critical"
        findings.append(
            ReviewFinding(
                "lookahead",
                severity,
                issue.detail,
                {"pattern": issue.pattern, "line": issue.line},
            )
        )
    return findings


def _universe_coverage_finding(coverage: dict[str, Any]) -> ReviewFinding:
    if not coverage.get("point_in_time"):
        return ReviewFinding(
            "universe_coverage",
            "pass",
            "Universe coverage audit is not required for a non-point-in-time universe.",
            coverage,
        )

    expected = int(coverage.get("expected_member_bars") or 0)
    observed = int(coverage.get("observed_member_bars") or 0)
    missing = int(coverage.get("missing_member_bars") or max(expected - observed, 0))
    missing_rate = float(coverage.get("missing_rate") or (missing / expected if expected else 0.0))
    missing_symbols = list(coverage.get("symbols_missing_entirely") or [])
    covers_delisted = bool(coverage.get("covers_delisted"))

    if expected <= 0:
        return ReviewFinding(
            "universe_coverage",
            "info",
            "Point-in-time universe coverage could not be evaluated because no expected member bars were counted.",
            coverage,
        )

    # A point-in-time universe that is missing most of its member data is barely
    # better than the survivorship-biased snapshot it replaces - reject it rather
    # than presenting it as merely "promising".
    if missing_rate > UNIVERSE_COVERAGE_MISSING_CRITICAL:
        return ReviewFinding(
            "universe_coverage",
            "critical",
            (
                "Point-in-time universe is missing the majority of member data; the sample is not "
                f"representative of the true historical universe ({observed}/{expected} member bars observed, "
                f"{missing_rate:.1%} missing, {len(missing_symbols)} symbols missing entirely)."
            ),
            coverage,
        )

    data_gap = missing_rate > UNIVERSE_COVERAGE_MISSING_WARNING or bool(missing_symbols)
    if not covers_delisted and not data_gap:
        # Coverage is otherwise fine; the only reason for the warning is that no
        # delisted-data source is configured. Make clear this cap is expected and
        # by design, not a signal that the factor is weak, so users don't read a
        # permanently-PROMISING point-in-time run as a factor-quality problem.
        return ReviewFinding(
            "universe_coverage",
            "warning",
            (
                "Point-in-time run is capped at PROMISING by design: no delisted-data source is configured "
                "(covers_delisted=false), so a small residual survivorship bias from unlisted members cannot be "
                f"ruled out. Data coverage is otherwise good ({observed}/{expected} member bars observed). This "
                "cap is expected, not a factor-quality problem, and lifts once a delisted-data source is added."
            ),
            coverage,
        )

    if (not covers_delisted) or data_gap:
        return ReviewFinding(
            "universe_coverage",
            "warning",
            (
                "Point-in-time universe has incomplete member data coverage; residual survivorship bias may remain "
                f"({observed}/{expected} member bars observed, {missing_rate:.1%} missing, "
                f"{len(missing_symbols)} symbols missing entirely)."
            ),
            coverage,
        )

    return ReviewFinding(
        "universe_coverage",
        "pass",
        f"Point-in-time universe member coverage is acceptable ({observed}/{expected} member bars observed).",
        coverage,
    )


def _funding_cost_finding(detail: dict[str, Any]) -> ReviewFinding:
    before = detail.get("sharpe_before_funding")
    after = detail.get("sharpe_after_funding")
    if before is None or after is None:
        return ReviewFinding("funding_cost_sensitivity", "info", "Funding cost sensitivity could not be evaluated.", detail)
    decay = float(before) - float(after)
    severity = "warning" if decay > 0.5 else "pass"
    message = (
        f"Funding-adjusted Sharpe changed from {float(before):.3f} to {float(after):.3f} "
        f"(decay {decay:.3f})."
    )
    return ReviewFinding("funding_cost_sensitivity", severity, message, detail)


def _oos_finding(result: OOSResult) -> ReviewFinding:
    detail = asdict(result)
    if result.train_observations < MIN_OOS_OBSERVATIONS or result.test_observations < MIN_OOS_OBSERVATIONS:
        return ReviewFinding("out_of_sample", "info", "Not enough observations to evaluate sample decay.", detail)
    train_sharpe = float(result.train_metrics.get("sharpe", 0.0) or 0.0)
    test_sharpe = float(result.test_metrics.get("sharpe", 0.0) or 0.0)
    if train_sharpe > 0.5 and test_sharpe < 0:
        return ReviewFinding("out_of_sample", "critical", "Out-of-sample Sharpe flipped negative versus positive train Sharpe.", detail)
    if train_sharpe > 0 and test_sharpe < 0:
        return ReviewFinding("out_of_sample", "warning", "Out-of-sample Sharpe flipped negative versus a (weak) positive train Sharpe.", detail)
    if result.sharpe_decay_ratio is not None and result.sharpe_decay_ratio < 0.5:
        return ReviewFinding("out_of_sample", "critical", "Out-of-sample Sharpe decayed by more than half.", detail)
    if result.sharpe_decay_ratio is not None and result.sharpe_decay_ratio < 0.8:
        return ReviewFinding("out_of_sample", "warning", "Out-of-sample Sharpe decayed materially.", detail)
    return ReviewFinding("out_of_sample", "pass", "Out-of-sample decay check did not flag material degradation.", detail)


def _cost_finding(result: CostSensitivityResult) -> ReviewFinding:
    values = result.sharpe_by_multiplier
    detail = {"sharpe_by_multiplier": {str(key): value for key, value in values.items()}}
    base = values.get(1.0, 0.0)
    one_half = values.get(1.5, 0.0)
    if result.unprofitable_at_2x:
        return ReviewFinding("cost_sensitivity", "warning", "Sharpe is non-positive under 2x assumed trading costs.", detail)
    if base > 0 and one_half / base < 0.5:
        return ReviewFinding("cost_sensitivity", "warning", "Sharpe drops by more than 50% under 1.5x assumed costs.", detail)
    return ReviewFinding("cost_sensitivity", "pass", "Trading-cost sensitivity did not breach warning thresholds.", detail)


def _parameter_finding(result: ParameterStabilityResult | None) -> ReviewFinding:
    if result is None:
        return ReviewFinding("parameter_stability", "info", "No perturbable numeric parameter literals were found.", {})
    detail = asdict(result)
    if result.sharpe_spread > PARAMETER_INSTABILITY_THRESHOLD:
        return ReviewFinding("parameter_stability", "warning", "Sharpe is sensitive to +/-20% numeric parameter perturbations.", detail)
    return ReviewFinding("parameter_stability", "pass", "Parameter perturbation did not breach the instability threshold.", detail)


def _dsr_finding(returns: pd.Series, n_trials: int, trial_sharpes: list[float] | None) -> ReviewFinding:
    periods = periods_per_year_from_timestamps(returns.index)
    result = deflated_sharpe_ratio(returns, n_trials=n_trials, trial_sharpes=trial_sharpes, periods_per_year=periods)
    detail = asdict(result)
    if n_trials <= 1:
        return ReviewFinding("deflated_sharpe", "info", "Single-trial run; multiple-testing deflation not applied.", detail)
    if result.n_observations < MIN_DSR_OBSERVATIONS:
        return ReviewFinding("deflated_sharpe", "info", "Not enough observations to evaluate deflated Sharpe ratio.", detail)
    if not result.is_significant:
        return ReviewFinding(
            "deflated_sharpe",
            "warning",
            "Sharpe is not significant after multiple-testing deflation.",
            detail,
        )
    return ReviewFinding("deflated_sharpe", "pass", "Sharpe remains significant after multiple-testing deflation.", detail)


def _pbo_finding(result: PBOResult) -> ReviewFinding:
    detail = asdict(result)
    if result.n_configs < 4 or not result.logits:
        return ReviewFinding("pbo_batch", "info", "Not enough candidate configurations to evaluate batch overfitting.", detail)
    if result.is_overfit:
        return ReviewFinding("pbo_batch", "warning", "Batch CSCV indicates elevated probability of backtest overfitting.", detail)
    return ReviewFinding("pbo_batch", "pass", "Batch CSCV did not indicate elevated overfitting probability.", detail)


def _walk_forward_finding(result: WalkForwardResult) -> ReviewFinding:
    detail = asdict(result)
    if result.n_windows < MIN_WALK_FORWARD_WINDOWS:
        return ReviewFinding("walk_forward", "info", "Not enough walk-forward windows to evaluate OOS distribution.", detail)
    if result.positive_window_share < 0.5:
        return ReviewFinding("walk_forward", "warning", "Most walk-forward OOS windows have non-positive Sharpe.", detail)
    return ReviewFinding("walk_forward", "pass", "Walk-forward OOS windows did not breach warning thresholds.", detail)


def _cpcv_finding(
    code: str,
    returns: pd.Series,
) -> ReviewFinding:
    lookback = estimate_lookback_bars(code, len(returns))
    result = run_cpcv(returns, lookback_bars=lookback.lookback_bars)
    detail = asdict(result)
    detail["lookback_bars"] = lookback.lookback_bars
    detail["lookback_source"] = lookback.source
    if result.n_paths < MIN_CPCV_PATHS:
        return ReviewFinding("cpcv", "info", "Not enough CPCV paths to evaluate purged OOS distribution.", detail)
    tail_note = ""
    if result.median_test_sharpe - result.p05_test_sharpe > 1.0:
        tail_note = " The CPCV OOS distribution has a heavy left tail."
    if result.positive_path_share < 0.5:
        return ReviewFinding("cpcv", "warning", "Most purged CPCV OOS paths have non-positive Sharpe." + tail_note, detail)
    return ReviewFinding("cpcv", "pass", "Purged CPCV OOS paths did not breach warning thresholds." + tail_note, detail)


def _ic_significance_finding(
    ic_series: pd.Series | None,
    ic_significance: ICSignificance | dict[str, Any] | None,
) -> ReviewFinding:
    if ic_significance is None and ic_series is None:
        return ReviewFinding("ic_significance", "info", "IC significance check applies only to cross-sectional runs.", {})
    if ic_significance is None and ic_series is not None:
        ic_significance = ic_newey_west(ic_series)
    detail = ic_significance.to_dict() if isinstance(ic_significance, ICSignificance) else dict(ic_significance or {})
    n_periods = int(detail.get("n_periods") or 0)
    t_stat = detail.get("t_stat")
    if n_periods < 10 or t_stat is None or pd.isna(t_stat):
        return ReviewFinding("ic_significance", "info", "Not enough IC observations to evaluate Newey-West significance.", detail)
    if not bool(detail.get("is_significant")):
        return ReviewFinding("ic_significance", "warning", "Rank IC is not statistically significant after Newey-West correction.", detail)
    return ReviewFinding("ic_significance", "pass", "Rank IC is statistically significant after Newey-West correction.", detail)


def _regime_finding(returns: pd.Series) -> ReviewFinding:
    contributions = yearly_return_contribution(returns)
    if len(contributions) < 2:
        return ReviewFinding("regime", "info", "Data does not cover enough calendar years to evaluate regime dependence.", {"yearly_contribution": contributions})
    year, contribution = max(contributions.items(), key=lambda item: abs(item[1]))
    detail = {"yearly_contribution": contributions, "max_year": year, "max_abs_contribution": abs(contribution)}
    if abs(contribution) > REGIME_CONCENTRATION_THRESHOLD:
        return ReviewFinding("regime", "warning", f"Return contribution is concentrated in {year}.", detail)
    return ReviewFinding("regime", "pass", "No single calendar year dominates return contribution.", detail)


def _tail_finding(returns: pd.Series) -> ReviewFinding:
    if len(returns.dropna()) < 20:
        return ReviewFinding("tail_dependence", "info", "Not enough return observations to evaluate tail dependence.", {})
    share = best_days_contribution_share(returns)
    detail = {"best_days_positive_return_share": share}
    if share > TAIL_DEPENDENCE_SHARE_WARNING:
        return ReviewFinding(
            "tail_dependence",
            "warning",
            f"The best handful of days (up to {MAX_BEST_DAYS}) account for {share:.0%} of all positive daily return.",
            detail,
        )
    return ReviewFinding("tail_dependence", "pass", "Positive return is not concentrated in the best 5% of days.", detail)


def _turnover_finding(turnover_annual: float | None) -> ReviewFinding:
    detail = {"turnover_annual": turnover_annual}
    if turnover_annual is None:
        return ReviewFinding("turnover", "info", "Turnover metric was unavailable.", detail)
    if turnover_annual > TURNOVER_ANNUAL_WARNING:
        return ReviewFinding("turnover", "warning", "Annualized turnover is high enough to raise implementation concerns.", detail)
    return ReviewFinding("turnover", "pass", "Annualized turnover is below the reviewer warning threshold.", detail)


def _beta_finding(
    returns: pd.Series, benchmark_returns: pd.Series | None, benchmark_symbol: str | None = None
) -> ReviewFinding:
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
        return ReviewFinding("beta_exposure", "warning", "Returns are substantially explained by benchmark beta exposure.", detail)
    return ReviewFinding("beta_exposure", "pass", "Benchmark beta exposure did not breach warning thresholds.", detail)


def _symbol_finding(factor_panel: pd.DataFrame, n_groups: int) -> ReviewFinding:
    share, top = symbol_concentration_from_factor_panel(factor_panel, n_groups)
    detail = {"top_5_abs_contribution_share": share, "top_symbols": top}
    if share > 0.5:
        return ReviewFinding("symbol_concentration", "warning", "Long-short returns are concentrated in a small number of symbols.", detail)
    return ReviewFinding("symbol_concentration", "pass", "Symbol-level contribution concentration is below the warning threshold.", detail)
