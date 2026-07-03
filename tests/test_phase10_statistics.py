import json
from pathlib import Path

import numpy as np
import pandas as pd


def _returns(seed: int = 7, rows: int = 320, mean: float = 0.0012) -> pd.Series:
    rng = np.random.default_rng(seed)
    index = pd.date_range("2023-01-01", periods=rows, freq="1D", tz="UTC")
    return pd.Series(rng.normal(mean, 0.01, rows), index=index)


def test_deflated_sharpe_penalizes_trial_count_monotonically():
    from quantbench.review.deflated_sharpe import deflated_sharpe_ratio

    returns = _returns()

    single = deflated_sharpe_ratio(returns, n_trials=1, periods_per_year=252)
    many = deflated_sharpe_ratio(returns, n_trials=25, periods_per_year=252)

    assert single.observed_sharpe == many.observed_sharpe
    assert many.expected_max_sharpe > single.expected_max_sharpe
    assert many.deflated_sharpe < single.deflated_sharpe
    assert many.n_trials == 25


def test_run_review_adds_dsr_finding_and_caps_non_significant_multi_trial_result():
    from quantbench.review import run_review

    returns = _returns(seed=11, rows=180, mean=0.0002)
    df = pd.DataFrame({"timestamp": returns.index, "close": 100 * (1 + returns).cumprod()})

    report = run_review(
        code="def compute(df):\n    return df['close'].pct_change(5).fillna(0.0)\n",
        returns=returns,
        cost_bps=0,
        rerun_at_cost=lambda bps: {"sharpe": 0.2},
        rerun_with_code=lambda candidate: {"sharpe": 0.2},
        out_of_sample_data=df,
        run_on_data=lambda data: {"sharpe": 0.2},
        n_trials=30,
        trial_sharpes=[0.1, 0.2, 0.15, 0.05],
        benchmark_returns=None,
        turnover_annual=10,
    )

    dsr = next(finding for finding in report.findings if finding.check == "deflated_sharpe")
    assert dsr.severity == "warning"
    assert report.verdict in {"PROMISING", "WEAK", "REJECTED"}


def test_pbo_returns_batch_overfit_probability_for_noise_configs():
    from quantbench.review.pbo import probability_of_backtest_overfitting

    rng = np.random.default_rng(9)
    index = pd.date_range("2022-01-01", periods=240, freq="1D", tz="UTC")
    matrix = pd.DataFrame(
        {f"noise_{i}": rng.normal(0.0, 0.01, len(index)) for i in range(20)},
        index=index,
    )

    result = probability_of_backtest_overfitting(matrix, n_splits=8)

    assert result.n_configs == 20
    assert result.n_splits == 8
    assert result.logits
    assert 0.0 <= result.pbo <= 1.0
    assert result.is_overfit is (result.pbo > 0.5)


def test_walk_forward_reports_oos_distribution():
    from quantbench.review.walk_forward import run_walk_forward

    index = pd.date_range("2021-01-01", periods=120, freq="1D", tz="UTC")
    rng = np.random.default_rng(5)
    # First half positive drift, second half negative -> two positive windows,
    # two negative windows, so positive_window_share is 0.5.
    values = np.concatenate(
        [rng.normal(0.01, 0.005, 60), rng.normal(-0.01, 0.005, 60)]
    )
    returns = pd.Series(values, index=index)

    result = run_walk_forward(returns, n_windows=4)

    assert result.n_windows == 4
    assert result.positive_window_share == 0.5
    assert result.window_test_sharpes[0] > 0 and result.window_test_sharpes[-1] < 0


def test_block_bootstrap_ci_contains_point_estimate():
    from quantbench.review.bootstrap import block_bootstrap_ci

    point, lower, upper = block_bootstrap_ci(_returns(seed=13), metric="sharpe", n_boot=250, block_size=12)

    assert lower <= point <= upper
    assert lower < upper


def test_trial_count_matches_universe_signature_and_overlapping_window(tmp_path: Path, monkeypatch):
    from quantbench.api import run_reader
    from quantbench.artifact.store import ArtifactStore
    from quantbench.library.trials import count_trials, universe_signature

    monkeypatch.setattr(run_reader, "RUNS_DIR", tmp_path / "runs")
    store = ArtifactStore(tmp_path / "runs")
    universe = {
        "asset_class": "equity",
        "source": "unit-test",
        "symbols": ["MSFT", "AAPL", "GOOG"],
    }
    sig = universe_signature(universe)
    for _ in range(2):
        run = store.create_run("trial")
        run.save_config({"universe": universe, "start": "2022-01-01", "end": "2022-12-31"})
        run.finalize(data_hash="d", code_hash="c", metrics={"sharpe": 0.1}, review={"verdict": "PROMISING", "findings": []})

    count = count_trials(sig, "2022-06-01", "2022-06-30")

    assert count.prior_trials == 2
    assert count.matched_run_ids


def test_backtest_json_includes_bootstrap_metric_intervals():
    from quantbench.engine.vectorized_backtest import run_vectorized_backtest

    df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2022-01-01", periods=160, freq="1D", tz="UTC"),
            "close": np.linspace(100, 140, 160) + np.sin(np.linspace(0, 10, 160)),
        }
    )
    signal = df["close"].pct_change(5).fillna(0.0)
    result = run_vectorized_backtest(df, signal, cost_bps=0)
    payload = result.to_json_dict()

    assert set(payload["metrics_ci"]) >= {"sharpe", "annual_return"}
    assert payload["metrics_ci"]["sharpe"]["lower"] <= payload["metrics"]["sharpe"] <= payload["metrics_ci"]["sharpe"]["upper"]
