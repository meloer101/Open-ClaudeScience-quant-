import numpy as np
import pandas as pd


def test_lookahead_factor_golden_is_rejected():
    from quantbench.engine.vectorized_backtest import run_vectorized_backtest
    from quantbench.review import run_review
    from quantbench.skills.codeexec import run_signal_code

    index = pd.date_range("2022-01-01", periods=180, freq="1D", tz="UTC")
    data = pd.DataFrame({"timestamp": index, "close": np.linspace(100, 140, len(index))})
    code = "def compute(df):\n    return df['close'].shift(-1).fillna(0.0)\n"
    signal = run_signal_code(code, data)
    result = run_vectorized_backtest(data, signal, cost_bps=0)

    report = run_review(
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

    assert report.verdict == "REJECTED"
    assert any(finding.check == "lookahead" and finding.severity == "critical" for finding in report.findings)


def test_noise_batch_golden_is_penalized_by_dsr_and_pbo():
    from quantbench.review.deflated_sharpe import deflated_sharpe_ratio
    from quantbench.review.pbo import probability_of_backtest_overfitting
    from quantbench.review.report import ReviewFinding, determine_verdict

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

    assert not dsr.is_significant
    assert pbo.pbo > 0.5
    assert determine_verdict(findings)[0] in {"PROMISING", "WEAK"}


def test_overfit_factor_golden_gets_dsr_and_walk_forward_warnings():
    from quantbench.review import run_review

    index = pd.date_range("2021-01-01", periods=160, freq="1D", tz="UTC")
    # Overfit factor with no real edge: a negative-drift OOS return stream makes
    # both the deflated Sharpe (under 25 trials) and the walk-forward window
    # distribution flag it.
    returns = pd.Series(np.random.default_rng(22).normal(-0.002, 0.01, len(index)), index=index)
    data = pd.DataFrame({"timestamp": index, "close": 100 * (1 + returns).cumprod()})

    report = run_review(
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

    severities = {finding.check: finding.severity for finding in report.findings}
    assert severities["deflated_sharpe"] == "warning"
    assert severities["walk_forward"] == "warning"
    assert report.verdict in {"WEAK", "PROMISING"}


def test_overfit_factor_golden_gets_cpcv_warning():
    from quantbench.review import run_review

    index = pd.date_range("2021-01-01", periods=300, freq="1D", tz="UTC")
    # An overfit factor whose out-of-sample edge is actually negative: every
    # combinatorial purged path lands non-positive, so CPCV must warn.
    returns = pd.Series(np.random.default_rng(23).normal(-0.002, 0.01, len(index)), index=index)
    data = pd.DataFrame({"timestamp": index, "close": 100 * (1 + returns).cumprod()})

    report = run_review(
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

    cpcv = next(finding for finding in report.findings if finding.check == "cpcv")
    assert cpcv.severity == "warning"
    assert cpcv.detail["positive_path_share"] < 0.5
    assert report.verdict in {"PROMISING", "WEAK"}


def test_single_trial_robust_factor_golden_is_not_dsr_penalized():
    from quantbench.review import run_review

    index = pd.date_range("2020-01-01", periods=260, freq="1D", tz="UTC")
    returns = pd.Series(np.full(len(index), 0.001), index=index)
    returns.iloc[::17] = -0.0005
    data = pd.DataFrame({"timestamp": index, "close": 100 * (1 + returns).cumprod()})

    report = run_review(
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
    from quantbench.review import run_review

    index = pd.date_range("2020-01-01", periods=520, freq="1D", tz="UTC")
    returns = pd.Series(0.0, index=index)
    returns.loc["2020"] = 0.001
    returns.loc["2021"] = 0.00001
    data = pd.DataFrame({"timestamp": index, "close": 100 * (1 + returns).cumprod()})

    report = run_review(
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
