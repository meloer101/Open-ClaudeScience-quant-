import numpy as np
import pandas as pd

from golden_run_registry import (
    build_lookahead_case,
    build_noise_batch_case,
    build_overfit_cpcv_case,
    build_overfit_dsr_walkforward_case,
    build_regime_concentrated_case,
    build_single_trial_robust_case,
)


def test_lookahead_factor_golden_is_rejected():
    report = build_lookahead_case()

    assert report.verdict == "REJECTED"
    assert any(finding.check == "lookahead" and finding.severity == "critical" for finding in report.findings)


def test_noise_batch_golden_is_penalized_by_dsr_and_pbo():
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

    report = build_noise_batch_case()

    assert not dsr.is_significant
    assert pbo.pbo > 0.5
    assert report.verdict in {"PROMISING", "WEAK"}


def test_overfit_factor_golden_gets_dsr_and_walk_forward_warnings():
    report = build_overfit_dsr_walkforward_case()

    severities = {finding.check: finding.severity for finding in report.findings}
    assert severities["deflated_sharpe"] == "warning"
    assert severities["walk_forward"] == "warning"
    assert report.verdict in {"WEAK", "PROMISING"}


def test_overfit_factor_golden_gets_cpcv_warning():
    report = build_overfit_cpcv_case()

    cpcv = next(finding for finding in report.findings if finding.check == "cpcv")
    assert cpcv.severity == "warning"
    assert cpcv.detail["positive_path_share"] < 0.5
    assert report.verdict in {"PROMISING", "WEAK"}


def test_single_trial_robust_factor_golden_is_not_dsr_penalized():
    report = build_single_trial_robust_case()

    dsr = next(finding for finding in report.findings if finding.check == "deflated_sharpe")
    assert dsr.severity == "info"
    assert report.verdict in {"STRONG", "PROMISING"}


def test_ic_newey_west_golden_separates_robust_ic_from_noise_winner():
    from quantbench.engine.metrics import ic_newey_west

    robust = pd.Series(np.full(80, 0.04) + np.random.default_rng(1).normal(0.0, 0.01, 80))
    rng = np.random.default_rng(52)
    noise_batch = {f"noise_{index}": pd.Series(rng.normal(0.0, 0.1, 60)) for index in range(20)}
    winner = noise_batch[max(noise_batch, key=lambda name: float(noise_batch[name].mean()))]

    assert ic_newey_west(robust).is_significant
    assert not ic_newey_west(winner).is_significant


def test_regime_factor_golden_warns_on_concentrated_year():
    report = build_regime_concentrated_case()

    assert any(finding.check == "regime" and finding.severity == "warning" for finding in report.findings)


def test_research_note_formats_sharpe_and_return_confidence_intervals():
    from quantbench.skills.report import build_research_note

    note = build_research_note(
        "run_test",
        {"model": "unit", "hypothesis": "ci formatting"},
        {"sharpe": 1.42, "annual_return": 0.18, "max_drawdown": -0.1},
        "sha256:test",
        metrics_ci={
            "sharpe": {"point": 1.42, "lower": 0.6, "upper": 2.1},
            "annual_return": {"point": 0.18, "lower": 0.04, "upper": 0.31},
        },
    )

    assert "sharpe | 1.42 [95% CI: 0.6, 2.1]" in note
    assert "annual_return | 0.18 [95% CI: 0.04, 0.31]" in note
