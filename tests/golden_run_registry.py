"""Golden-run registry for GAP 5.1 regression discipline.

Not a test module itself (no `test_` prefix, pytest won't collect it) - it is
imported by tests/test_phase10_golden_runs.py (which keeps its original
per-scenario assertions, now sourced from these builders) and by
tests/test_golden_run_discipline.py (which runs every case and asserts none
drifted from its expected verdict/findings).

Each builder reproduces exactly the fixture construction that previously
lived inline in test_phase10_golden_runs.py - this is a pure extraction, not
a rewrite, so the golden scenarios themselves are unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from quantbench.review import ReviewFinding, ReviewReport, determine_verdict, run_review


@dataclass(frozen=True)
class GoldenCase:
    name: str
    category: str
    build: Callable[[], ReviewReport]
    expected_verdicts: frozenset[str]
    required_findings: dict[str, str]


@dataclass(frozen=True)
class GoldenCaseResult:
    name: str
    category: str
    expected_verdicts: frozenset[str]
    actual_verdict: str
    verdict_ok: bool
    finding_mismatches: list[str]


def build_lookahead_case() -> ReviewReport:
    from quantbench.engine.vectorized_backtest import run_vectorized_backtest
    from quantbench.skills.codeexec import run_signal_code

    index = pd.date_range("2022-01-01", periods=180, freq="1D", tz="UTC")
    data = pd.DataFrame({"timestamp": index, "close": np.linspace(100, 140, len(index))})
    code = "def compute(df):\n    return df['close'].shift(-1).fillna(0.0)\n"
    signal = run_signal_code(code, data)
    result = run_vectorized_backtest(data, signal, cost_bps=0)

    return run_review(
        code=code,
        returns=result.returns,
        cost_bps=0,
        rerun_at_cost=lambda bps: result.metrics,
        rerun_with_code=lambda candidate: result.metrics,
        out_of_sample_data=data,
        run_on_data=lambda frame: result.metrics,
        benchmark_returns=None,
        turnover_annual=result.metrics["turnover_annual"],
    )


def build_noise_batch_case() -> ReviewReport:
    from quantbench.review.deflated_sharpe import deflated_sharpe_ratio
    from quantbench.review.pbo import probability_of_backtest_overfitting

    index = pd.date_range("2020-01-01", periods=240, freq="1D", tz="UTC")
    rows_per_block = 30
    columns = {}
    for config_index in range(20):
        values = np.full(len(index), -0.001)
        block_index = config_index % 8
        values[block_index * rows_per_block : (block_index + 1) * rows_per_block] = 0.01
        values += np.random.default_rng(config_index).normal(0.0, 0.001, len(index))
        columns[f"overfit_{config_index}"] = values
    noise = pd.DataFrame(columns, index=index)
    sharpe_by_column = {
        column: float(series.mean() / series.std(ddof=0) * np.sqrt(252))
        for column, series in noise.items()
        if series.std(ddof=0) > 0
    }
    sharpes = list(sharpe_by_column.values())
    winner = noise[max(sharpe_by_column, key=sharpe_by_column.get)]

    dsr = deflated_sharpe_ratio(winner, n_trials=20, trial_sharpes=sharpes, periods_per_year=252)
    pbo = probability_of_backtest_overfitting(noise, n_splits=8)
    findings = [
        ReviewFinding("deflated_sharpe", "warning" if not dsr.is_significant else "pass", "dsr", dsr.__dict__),
        ReviewFinding("pbo_batch", "warning" if pbo.is_overfit else "pass", "pbo", pbo.__dict__),
    ]
    verdict, reason = determine_verdict(findings)
    return ReviewReport(findings=findings, verdict=verdict, verdict_reason=reason)


def build_overfit_dsr_walkforward_case() -> ReviewReport:
    index = pd.date_range("2021-01-01", periods=160, freq="1D", tz="UTC")
    # Overfit factor with no real edge: a negative-drift OOS return stream makes
    # both the deflated Sharpe (under 25 trials) and the walk-forward window
    # distribution flag it.
    returns = pd.Series(np.random.default_rng(22).normal(-0.002, 0.01, len(index)), index=index)
    data = pd.DataFrame({"timestamp": index, "close": 100 * (1 + returns).cumprod()})

    return run_review(
        code="def compute(df):\n    return df['close'].pct_change(20).fillna(0.0)\n",
        returns=returns,
        cost_bps=0,
        rerun_at_cost=lambda bps: {"sharpe": 0.2},
        rerun_with_code=lambda candidate: {"sharpe": 0.2},
        out_of_sample_data=data,
        run_on_data=lambda frame: {"sharpe": -1.0},
        n_trials=25,
        trial_sharpes=[0.1, 0.2, 0.05, -0.1],
        benchmark_returns=None,
        turnover_annual=10,
    )


def build_overfit_cpcv_case() -> ReviewReport:
    index = pd.date_range("2021-01-01", periods=300, freq="1D", tz="UTC")
    # An overfit factor whose out-of-sample edge is actually negative: every
    # combinatorial purged path lands non-positive, so CPCV must warn.
    returns = pd.Series(np.random.default_rng(23).normal(-0.002, 0.01, len(index)), index=index)
    data = pd.DataFrame({"timestamp": index, "close": 100 * (1 + returns).cumprod()})

    return run_review(
        code="def compute(df):\n    return df['close'].pct_change(20).fillna(0.0)\n",
        returns=returns,
        cost_bps=0,
        rerun_at_cost=lambda bps: {"sharpe": 0.2},
        rerun_with_code=lambda candidate: {"sharpe": 0.2},
        out_of_sample_data=data,
        run_on_data=lambda frame: {"sharpe": -1.0},
        benchmark_returns=None,
        turnover_annual=10,
    )


def build_single_trial_robust_case() -> ReviewReport:
    index = pd.date_range("2020-01-01", periods=260, freq="1D", tz="UTC")
    returns = pd.Series(np.full(len(index), 0.001), index=index)
    returns.iloc[::17] = -0.0005
    data = pd.DataFrame({"timestamp": index, "close": 100 * (1 + returns).cumprod()})

    return run_review(
        code="def compute(df):\n    return df['close'].pct_change(20).fillna(0.0)\n",
        returns=returns,
        cost_bps=0,
        rerun_at_cost=lambda bps: {"sharpe": 1.0},
        rerun_with_code=lambda candidate: {"sharpe": 1.0},
        out_of_sample_data=data,
        run_on_data=lambda frame: {"sharpe": 1.0},
        benchmark_returns=None,
        turnover_annual=10,
    )


def build_regime_concentrated_case() -> ReviewReport:
    index = pd.date_range("2020-01-01", periods=520, freq="1D", tz="UTC")
    returns = pd.Series(0.0, index=index)
    returns.loc["2020"] = 0.001
    returns.loc["2021"] = 0.00001
    data = pd.DataFrame({"timestamp": index, "close": 100 * (1 + returns).cumprod()})

    return run_review(
        code="def compute(df):\n    return df['close'].pct_change(20).fillna(0.0)\n",
        returns=returns,
        cost_bps=0,
        rerun_at_cost=lambda bps: {"sharpe": 1.0},
        rerun_with_code=lambda candidate: {"sharpe": 1.0},
        out_of_sample_data=data,
        run_on_data=lambda frame: {"sharpe": 1.0},
        benchmark_returns=None,
        turnover_annual=10,
    )


GOLDEN_CASES: list[GoldenCase] = [
    GoldenCase(
        name="lookahead_factor",
        category="lookahead",
        build=build_lookahead_case,
        expected_verdicts=frozenset({"REJECTED"}),
        required_findings={"lookahead": "critical"},
    ),
    GoldenCase(
        name="noise_batch_dsr_pbo",
        category="overfit",
        build=build_noise_batch_case,
        expected_verdicts=frozenset({"PROMISING", "WEAK"}),
        required_findings={"deflated_sharpe": "warning", "pbo_batch": "warning"},
    ),
    GoldenCase(
        name="overfit_dsr_walkforward",
        category="overfit",
        build=build_overfit_dsr_walkforward_case,
        expected_verdicts=frozenset({"WEAK", "PROMISING"}),
        required_findings={"deflated_sharpe": "warning", "walk_forward": "warning"},
    ),
    GoldenCase(
        name="overfit_cpcv",
        category="overfit",
        build=build_overfit_cpcv_case,
        expected_verdicts=frozenset({"PROMISING", "WEAK"}),
        required_findings={"cpcv": "warning"},
    ),
    GoldenCase(
        name="single_trial_robust",
        category="robust_classic",
        build=build_single_trial_robust_case,
        expected_verdicts=frozenset({"STRONG", "PROMISING"}),
        required_findings={"deflated_sharpe": "info"},
    ),
    GoldenCase(
        name="regime_concentrated",
        category="regime",
        build=build_regime_concentrated_case,
        expected_verdicts=frozenset(),  # this scenario only asserts a finding, not a verdict bucket
        required_findings={"regime": "warning"},
    ),
]

REQUIRED_CATEGORIES = frozenset({"lookahead", "overfit", "robust_classic", "regime"})


def evaluate_case(case: GoldenCase) -> GoldenCaseResult:
    report = case.build()
    severities = {finding.check: finding.severity for finding in report.findings}
    mismatches: list[str] = []
    for check, expected_severity in case.required_findings.items():
        actual_severity = severities.get(check)
        if actual_severity != expected_severity:
            mismatches.append(f"{check}: expected severity={expected_severity!r}, got {actual_severity!r}")
    verdict_ok = not case.expected_verdicts or report.verdict in case.expected_verdicts
    return GoldenCaseResult(
        name=case.name,
        category=case.category,
        expected_verdicts=case.expected_verdicts,
        actual_verdict=report.verdict,
        verdict_ok=verdict_ok,
        finding_mismatches=mismatches,
    )


def render_summary(results: list[GoldenCaseResult]) -> str:
    lines = ["| case | category | expected verdict | actual verdict | status |", "|---|---|---|---|---|"]
    for result in results:
        expected = "/".join(sorted(result.expected_verdicts)) or "(finding-only)"
        ok = result.verdict_ok and not result.finding_mismatches
        status = "PASS" if ok else "FAIL"
        lines.append(f"| {result.name} | {result.category} | {expected} | {result.actual_verdict} | {status} |")

    failures = [result for result in results if not result.verdict_ok or result.finding_mismatches]
    if failures:
        lines.append("")
        lines.append("### Mismatches")
        for result in failures:
            if not result.verdict_ok:
                lines.append(
                    f"- **{result.name}**: expected verdict in {sorted(result.expected_verdicts)}, "
                    f"got {result.actual_verdict!r}"
                )
            for mismatch in result.finding_mismatches:
                lines.append(f"- **{result.name}**: {mismatch}")
    return "\n".join(lines)
