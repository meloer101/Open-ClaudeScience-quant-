import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from _fakes import FakeLLMClient


@pytest.fixture(autouse=True)
def _patch_runs_dir(tmp_path, monkeypatch):
    # run_reader resolves run directories via its own module-level RUNS_DIR
    # constant, independent of whichever ArtifactStore(tmp_path) a test
    # constructs - anything that goes through read_returns_series/
    # infer_asset_class (i.e. everything optimize_portfolio touches) needs
    # this patched or it silently reads/misses files in the real project
    # runs/ directory instead of the test's tmp_path.
    monkeypatch.setattr("quantbench.api.run_reader.RUNS_DIR", tmp_path / "runs")


def _idx(n: int, start: str = "2022-01-01") -> pd.DatetimeIndex:
    return pd.date_range(start, periods=n, freq="1D", tz="UTC")


def _series(values: np.ndarray, index: pd.DatetimeIndex) -> pd.Series:
    return pd.Series(values, index=index)


class JsonCriticLLM:
    def __init__(self, payload: dict | None = None):
        self.payload = payload or {
            "verdict": "PROMISING",
            "agrees_with_deterministic_verdict": True,
            "critique": "consistent",
            "narrative_consistency_issues": [],
            "recommended_next_steps": [],
        }
        self.calls: list = []

    def chat(self, messages, tools=None):
        self.calls.append((messages, tools))
        message = SimpleNamespace(role="assistant", content=json.dumps(self.payload), tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class BrokenCriticLLM:
    def chat(self, messages, tools=None):
        raise RuntimeError("critic unavailable")


# ---------------------------------------------------------------------------
# quantbench/portfolio/optimize.py
# ---------------------------------------------------------------------------


def test_equal_weight_and_inverse_variance_are_closed_form():
    from quantbench.portfolio.optimize import optimize

    np.random.seed(0)
    idx = _idx(300)
    returns = pd.DataFrame(
        {
            "a": np.random.normal(0.0005, 0.01, 300),
            "b": np.random.normal(0.0003, 0.03, 300),
            "c": np.random.normal(0.0002, 0.02, 300),
        },
        index=idx,
    )

    equal = optimize(returns, "equal_weight")
    assert equal.weights == pytest.approx({"a": 1 / 3, "b": 1 / 3, "c": 1 / 3})

    inv_var = optimize(returns, "inverse_variance", max_weight=1.0)
    # Lower-variance factor should always receive a strictly larger weight than
    # a higher-variance one under inverse-variance weighting.
    assert inv_var.weights["a"] > inv_var.weights["c"] > inv_var.weights["b"]
    assert sum(inv_var.weights.values()) == pytest.approx(1.0)


def test_all_methods_sum_to_one_and_respect_max_weight():
    from quantbench.portfolio.optimize import PORTFOLIO_METHODS, optimize

    np.random.seed(1)
    idx = _idx(250)
    returns = pd.DataFrame({name: np.random.normal(0.0002, 0.01 + i * 0.003, 250) for i, name in enumerate("abcde")}, index=idx)

    for method in PORTFOLIO_METHODS:
        # max_weight=0.4 > 1/5, so the cap binds as-is for every method,
        # including the closed-form ones (inverse_variance/hrp) that have no
        # optimizer-level bounds constraint of their own.
        result = optimize(returns, method, max_weight=0.4)
        assert sum(result.weights.values()) == pytest.approx(1.0, abs=1e-6)
        for name, weight in result.weights.items():
            assert weight >= -1e-9
            assert weight <= 0.4 + 1e-6


def test_single_factor_is_degenerate_full_weight():
    from quantbench.portfolio.optimize import optimize

    idx = _idx(100)
    returns = pd.DataFrame({"only": np.random.normal(0, 0.01, 100)}, index=idx)
    result = optimize(returns, "risk_parity", max_weight=0.6)
    assert result.weights == {"only": 1.0}
    assert result.diagnostics["degenerate"] == "single_factor"


def test_max_sharpe_flags_all_negative_expected_returns():
    from quantbench.portfolio.optimize import optimize

    idx = _idx(200)
    np.random.seed(2)
    returns = pd.DataFrame(
        {"a": -np.abs(np.random.normal(0.001, 0.005, 200)), "b": -np.abs(np.random.normal(0.0005, 0.01, 200))}, index=idx
    )
    result = optimize(returns, "max_sharpe", max_weight=0.9)
    assert sum(result.weights.values()) == pytest.approx(1.0)
    assert "warning" in result.diagnostics


def test_hrp_clusters_highly_correlated_pair_together():
    from quantbench.portfolio.optimize import optimize

    np.random.seed(3)
    idx = _idx(400)
    base = np.random.normal(0, 0.01, 400)
    a = base + np.random.normal(0, 0.0005, 400)
    b = base + np.random.normal(0, 0.0005, 400)  # near-duplicate of a
    c = np.random.normal(0, 0.02, 400)  # independent, higher vol
    returns = pd.DataFrame({"a": a, "b": b, "c": c}, index=idx)

    result = optimize(returns, "hrp", max_weight=1.0)
    assert sum(result.weights.values()) == pytest.approx(1.0, abs=1e-6)
    # a and b are near-duplicates of each other, so HRP should split risk
    # budget between them roughly evenly rather than favoring one.
    assert result.weights["a"] == pytest.approx(result.weights["b"], rel=0.25)


def test_ledoit_wolf_covariance_is_positive_semidefinite_under_near_singular_input():
    from quantbench.portfolio.optimize import ledoit_wolf_covariance

    np.random.seed(4)
    idx = _idx(150)
    a = np.random.normal(0, 0.01, 150)
    b = a + np.random.normal(0, 1e-6, 150)  # near-duplicate -> near-singular sample covariance
    returns = pd.DataFrame({"a": a, "b": b}, index=idx)

    cov, shrinkage = ledoit_wolf_covariance(returns)
    eigenvalues = np.linalg.eigvalsh(cov)
    assert (eigenvalues >= -1e-12).all()
    assert 0.0 <= shrinkage <= 1.0


# ---------------------------------------------------------------------------
# quantbench/portfolio/combine.py
# ---------------------------------------------------------------------------


def test_combine_anti_correlated_factors_reduces_volatility():
    from quantbench.portfolio.combine import combine

    idx = _idx(300)
    np.random.seed(5)
    noise = np.random.normal(0, 0.01, 300)
    a = 0.0003 + noise
    b = 0.0003 - noise  # perfectly anti-correlated with a
    returns = pd.DataFrame({"a": a, "b": b}, index=idx)

    combined = combine(returns, {"a": 0.5, "b": 0.5}, cost_bps=0)
    assert combined.metrics["diversification_ratio"] > 1.5
    assert combined.returns.std() < returns["a"].std()


def test_combine_to_json_dict_round_trips_through_run_reader(tmp_path: Path, monkeypatch):
    from quantbench.artifact.store import ArtifactStore
    from quantbench.portfolio.combine import combine

    monkeypatch.setattr("quantbench.config.RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr("quantbench.api.run_reader.RUNS_DIR", tmp_path / "runs")

    idx = _idx(120)
    returns = pd.DataFrame({"a": np.random.normal(0, 0.01, 120), "b": np.random.normal(0, 0.01, 120)}, index=idx)
    combined = combine(returns, {"a": 0.6, "b": 0.4}, cost_bps=5)

    store = ArtifactStore(tmp_path / "runs")
    run = store.create_run("fake portfolio")
    run.save_json("backtest_result.json", combined.to_json_dict())

    from quantbench.api import run_reader

    read_back = run_reader.read_returns_series(run.run_id)
    assert read_back is not None
    assert len(read_back) == len(combined.returns.dropna())


def test_combine_rejects_empty_returns():
    from quantbench.portfolio.combine import combine

    with pytest.raises(ValueError):
        combine(pd.DataFrame(), {"a": 1.0})


# ---------------------------------------------------------------------------
# quantbench/portfolio/pipeline.py
# ---------------------------------------------------------------------------


def test_pipeline_requires_at_least_two_overlapping_columns():
    from quantbench.portfolio.pipeline import run_portfolio_pipeline

    idx = _idx(100)
    with pytest.raises(ValueError):
        run_portfolio_pipeline(
            {"only": _series(np.random.normal(0, 0.01, 100), idx)},
            method="risk_parity",
            cost_bps=0,
            split=0.7,
            max_weight=0.6,
        )


def test_pipeline_comparison_table_covers_every_method():
    from quantbench.portfolio.optimize import PORTFOLIO_METHODS
    from quantbench.portfolio.pipeline import run_portfolio_pipeline

    np.random.seed(6)
    idx = _idx(200)
    returns_by_run = {
        "run_a": _series(np.random.normal(0.0004, 0.01, 200), idx),
        "run_b": _series(np.random.normal(0.0002, 0.015, 200), idx),
        "run_c": _series(np.random.normal(0.0001, 0.02, 200), idx),
    }
    outcome = run_portfolio_pipeline(returns_by_run, method="risk_parity", cost_bps=5, split=0.7, max_weight=0.6)

    assert set(outcome.comparison_table.keys()) == set(PORTFOLIO_METHODS)
    for row in outcome.comparison_table.values():
        # comparison_table rounds each weight to 6dp for JSON readability, so
        # the sum can be off from 1.0 by a few times that rounding step.
        assert sum(row["weights"].values()) == pytest.approx(1.0, abs=1e-4)
        assert row["train_sharpe"] is not None
        assert row["test_sharpe"] is not None
    assert outcome.overlap_observations == 200
    assert outcome.review_report.verdict in {"STRONG", "PROMISING", "WEAK", "REJECTED"}


def test_pipeline_headline_weights_are_unrounded_not_the_display_copy(monkeypatch):
    # Regression: run_portfolio_pipeline used to pull the selected method's
    # weights back out of comparison_table, which rounds to 6dp for JSON
    # display - the headline combine()/Reviewer calls must use the
    # optimizer's raw OptimizationResult.weights instead.
    import quantbench.portfolio.pipeline as pipeline_module
    from quantbench.portfolio.optimize import OptimizationResult

    idx = _idx(200)
    returns_by_run = {
        "a": _series(np.random.normal(0.0003, 0.01, 200), idx),
        "b": _series(np.random.normal(0.0002, 0.01, 200), idx),
    }
    precise_weight = 1 / 3  # 0.3333333333333333 - differs from round(_, 6)
    fake_result = OptimizationResult(method="risk_parity", weights={"a": precise_weight, "b": 1 - precise_weight}, diagnostics={})
    monkeypatch.setattr(pipeline_module, "evaluate_all_methods", lambda train, *, max_weight=1.0: {"risk_parity": fake_result})

    outcome = pipeline_module.run_portfolio_pipeline(returns_by_run, method="risk_parity", cost_bps=0, split=0.7, max_weight=1.0)

    assert outcome.weights["a"] == precise_weight
    assert outcome.weights["a"] != round(precise_weight, 6)
    assert outcome.comparison_table["risk_parity"]["weights"]["a"] == round(precise_weight, 6)


# ---------------------------------------------------------------------------
# quantbench/portfolio/review.py
# ---------------------------------------------------------------------------


def test_portfolio_out_of_sample_finding_flags_negative_flip():
    from quantbench.portfolio.combine import combine
    from quantbench.portfolio.review import run_portfolio_review

    idx = _idx(200)
    np.random.seed(7)
    returns = pd.DataFrame({"a": np.random.normal(0.001, 0.01, 200), "b": np.random.normal(0.0008, 0.012, 200)}, index=idx)
    weights = {"a": 0.5, "b": 0.5}
    combined = combine(returns, weights, cost_bps=0)

    train_returns = pd.Series(np.random.normal(0.002, 0.005, 60), index=_idx(60))
    test_returns = pd.Series(np.random.normal(-0.002, 0.005, 60), index=_idx(60, start="2022-03-01"))

    report = run_portfolio_review(
        returns=returns, weights=weights, method="risk_parity", combined=combined, train_returns=train_returns, test_returns=test_returns
    )
    finding = next(f for f in report.findings if f.check == "portfolio_out_of_sample")
    assert finding.severity in {"warning", "critical"}


def test_portfolio_out_of_sample_finding_passes_when_stable():
    from quantbench.portfolio.combine import combine
    from quantbench.portfolio.review import run_portfolio_review

    idx = _idx(200)
    np.random.seed(8)
    returns = pd.DataFrame({"a": np.random.normal(0.001, 0.01, 200), "b": np.random.normal(0.0008, 0.012, 200)}, index=idx)
    weights = {"a": 0.5, "b": 0.5}
    combined = combine(returns, weights, cost_bps=0)

    np.random.seed(9)
    train_returns = pd.Series(np.random.normal(0.001, 0.008, 60), index=_idx(60))
    test_returns = pd.Series(np.random.normal(0.001, 0.008, 60), index=_idx(60, start="2022-03-01"))

    report = run_portfolio_review(
        returns=returns, weights=weights, method="risk_parity", combined=combined, train_returns=train_returns, test_returns=test_returns
    )
    finding = next(f for f in report.findings if f.check == "portfolio_out_of_sample")
    assert finding.severity in {"pass", "info"}


def test_weight_stability_finding_flags_dominant_low_noise_factor():
    from quantbench.portfolio.combine import combine
    from quantbench.portfolio.review import run_portfolio_review

    idx = _idx(200)
    np.random.seed(10)
    # 'a' is an almost noiseless steady climb (astronomically high own-Sharpe),
    # so a +/-20% weight perturbation on it should swing the portfolio Sharpe a lot.
    a = np.full(200, 0.01) + np.random.normal(0, 1e-6, 200)
    b = np.random.normal(0, 0.02, 200)
    returns = pd.DataFrame({"a": a, "b": b}, index=idx)
    weights = {"a": 0.5, "b": 0.5}
    combined = combine(returns, weights, cost_bps=0)

    report = run_portfolio_review(returns=returns, weights=weights, method="risk_parity", combined=combined, train_returns=None, test_returns=None)
    finding = next(f for f in report.findings if f.check == "weight_stability")
    assert finding.severity == "warning"


def test_factor_concentration_finding_flags_dominant_weight():
    from quantbench.portfolio.combine import combine
    from quantbench.portfolio.review import run_portfolio_review

    idx = _idx(200)
    np.random.seed(11)
    returns = pd.DataFrame({"a": np.random.normal(0, 0.01, 200), "b": np.random.normal(0, 0.01, 200)}, index=idx)
    weights = {"a": 0.9, "b": 0.1}
    combined = combine(returns, weights, cost_bps=0)

    report = run_portfolio_review(returns=returns, weights=weights, method="risk_parity", combined=combined, train_returns=None, test_returns=None)
    finding = next(f for f in report.findings if f.check == "factor_concentration")
    assert finding.severity == "warning"


def test_factor_concentration_finding_passes_for_balanced_uncorrelated_weights():
    from quantbench.portfolio.combine import combine
    from quantbench.portfolio.review import run_portfolio_review

    idx = _idx(200)
    np.random.seed(12)
    # Three independent, similar-vol factors at roughly equal weight: no two-way
    # split can land exactly on the 0.5 threshold by sampling noise the way it
    # would with only two factors, so this is a robust "clearly not concentrated" case.
    returns = pd.DataFrame(
        {
            "a": np.random.normal(0, 0.01, 200),
            "b": np.random.normal(0, 0.01, 200),
            "c": np.random.normal(0, 0.01, 200),
        },
        index=idx,
    )
    weights = {"a": 1 / 3, "b": 1 / 3, "c": 1 / 3}
    combined = combine(returns, weights, cost_bps=0)

    report = run_portfolio_review(returns=returns, weights=weights, method="risk_parity", combined=combined, train_returns=None, test_returns=None)
    finding = next(f for f in report.findings if f.check == "factor_concentration")
    assert finding.severity == "pass"


def test_correlation_health_finding_flags_highly_correlated_factors():
    from quantbench.portfolio.combine import combine
    from quantbench.portfolio.review import run_portfolio_review

    idx = _idx(200)
    np.random.seed(13)
    base = np.random.normal(0, 0.01, 200)
    returns = pd.DataFrame({"a": base, "b": base + np.random.normal(0, 0.0005, 200)}, index=idx)
    weights = {"a": 0.5, "b": 0.5}
    combined = combine(returns, weights, cost_bps=0)

    report = run_portfolio_review(returns=returns, weights=weights, method="risk_parity", combined=combined, train_returns=None, test_returns=None)
    finding = next(f for f in report.findings if f.check == "correlation_health")
    assert finding.severity == "warning"


def test_correlation_health_finding_catches_one_redundant_pair_even_when_average_looks_fine():
    # Regression: A and B are near-duplicates (corr ~0.999) but C is
    # independent of both, so the *average* of the three pairwise
    # correlations (~0.32) sits well under the warning threshold even though
    # A/B are clearly redundant with each other. max_pairwise_abs_correlation
    # must catch this even when the average doesn't.
    from quantbench.portfolio.combine import combine
    from quantbench.portfolio.review import run_portfolio_review

    idx = _idx(200)
    np.random.seed(20)
    a = np.random.normal(0, 0.01, 200)
    b = a + np.random.normal(0, 0.0005, 200)
    c = np.random.normal(0, 0.01, 200)
    returns = pd.DataFrame({"a": a, "b": b, "c": c}, index=idx)
    weights = {"a": 1 / 3, "b": 1 / 3, "c": 1 / 3}
    combined = combine(returns, weights, cost_bps=0)

    report = run_portfolio_review(
        returns=returns, weights=weights, method="risk_parity", combined=combined, train_returns=None, test_returns=None
    )
    finding = next(f for f in report.findings if f.check == "correlation_health")
    assert finding.detail["average_pairwise_correlation"] < 0.7
    assert finding.detail["max_pairwise_abs_correlation"] > 0.9
    assert finding.severity == "warning"


def test_improvement_over_best_single_finding_flags_no_improvement():
    from quantbench.portfolio.combine import combine
    from quantbench.portfolio.review import run_portfolio_review

    idx = _idx(200)
    np.random.seed(14)
    good = np.random.normal(0.002, 0.008, 200)
    bad = np.random.normal(-0.002, 0.008, 200)
    returns = pd.DataFrame({"good": good, "bad": bad}, index=idx)
    # Heavily weighting the bad factor should drag the portfolio below the
    # good factor's own Sharpe.
    weights = {"good": 0.2, "bad": 0.8}
    combined = combine(returns, weights, cost_bps=0)

    report = run_portfolio_review(returns=returns, weights=weights, method="risk_parity", combined=combined, train_returns=None, test_returns=None)
    finding = next(f for f in report.findings if f.check == "improvement_over_best_single")
    assert finding.severity == "warning"


# ---------------------------------------------------------------------------
# quantbench/api/run_reader.py
# ---------------------------------------------------------------------------


def test_infer_asset_class_from_universe_and_provider(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("quantbench.api.run_reader.RUNS_DIR", tmp_path / "runs")
    from quantbench.artifact.store import ArtifactStore

    store = ArtifactStore(tmp_path / "runs")
    cross_run = store.create_run("cross")
    cross_run.save_config({"universe": {"asset_class": "crypto"}})

    single_run = store.create_run("single")
    single_run.save_config({"cache": {"provider": "yfinance_equity"}})

    crypto_single_run = store.create_run("crypto_single")
    crypto_single_run.save_config({"cache": {"provider": "ccxt_binance"}})

    from quantbench.api import run_reader

    assert run_reader.infer_asset_class(cross_run.run_id) == "crypto"
    assert run_reader.infer_asset_class(single_run.run_id) == "equity"
    assert run_reader.infer_asset_class(crypto_single_run.run_id) == "crypto"


# ---------------------------------------------------------------------------
# Coordinator integration
# ---------------------------------------------------------------------------


def _sample_ohlcv(rows: int = 180, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    timestamp = pd.date_range("2022-01-01", periods=rows, freq="1D", tz="UTC")
    close = 100 + np.cumsum(rng.normal(0.05, 1.0, rows))
    return pd.DataFrame(
        {
            "timestamp": timestamp,
            "open": close - 0.2,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": 1000.0,
        }
    )


def _make_constituent_run(store, monkeypatch, df: pd.DataFrame, signal_code: str, request_text: str):
    from quantbench.agent.coordinator import Coordinator

    def fake_fetch_ohlcv(symbol, timeframe, start, end):
        # Real fetch_ohlcv always includes "provider" in cache_meta (see
        # quantbench/data/exchange.py) - infer_asset_class() depends on it to
        # resolve a single-symbol run's asset class, so the fake must too.
        return None, df, {"source": "unit-test", "provider": "yfinance_equity", "cache_hit": False}

    monkeypatch.setattr("quantbench.agent.coordinator.fetch_ohlcv", fake_fetch_ohlcv)
    script = [
        ("tools", [("fetch_ohlcv", {"symbol": "AAPL", "timeframe": "1d", "start": "2022-01-01", "end": "2022-07-01"})]),
        ("tools", [("run_signal_backtest", {"code": signal_code, "cost_bps": 0})]),
        ("text", "done"),
    ]
    return Coordinator(run_store=store, llm=FakeLLMClient(script), critic_llm=JsonCriticLLM()).run(request_text)


def test_optimize_portfolio_direct_call_end_to_end(tmp_path: Path, monkeypatch):
    from quantbench.artifact.store import ArtifactStore
    from quantbench.agent.coordinator import Coordinator

    store = ArtifactStore(tmp_path / "runs")
    run_a = _make_constituent_run(
        store, monkeypatch, _sample_ohlcv(seed=1), "def compute(df):\n    return df['close'].pct_change(5).fillna(0.0)\n", "factor a"
    )
    run_b = _make_constituent_run(
        store, monkeypatch, _sample_ohlcv(seed=2), "def compute(df):\n    return -df['close'].pct_change(10).fillna(0.0)\n", "factor b"
    )

    portfolio = Coordinator(run_store=store, critic_llm=JsonCriticLLM()).optimize_portfolio(
        [run_a.run_id, run_b.run_id], method="risk_parity"
    )

    run_dir = portfolio.run_dir
    assert (run_dir / "portfolio_weights.json").exists()
    assert (run_dir / "portfolio_summary.json").exists()
    assert (run_dir / "backtest_result.json").exists()
    assert (run_dir / "review_report.json").exists()
    assert (run_dir / "critic_report.json").exists()
    assert (run_dir / "research_note.md").exists()

    weights = json.loads((run_dir / "portfolio_weights.json").read_text(encoding="utf-8"))
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-6)

    summary = json.loads((run_dir / "portfolio_summary.json").read_text(encoding="utf-8"))
    assert summary["selected_method"] == "risk_parity"
    assert set(summary["constituent_run_ids"]) == {run_a.run_id, run_b.run_id}

    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["review"]["verdict"] in {"STRONG", "PROMISING", "WEAK", "REJECTED"}
    assert manifest["critic"]["status"] == "ok"

    note = (run_dir / "research_note.md").read_text(encoding="utf-8")
    assert "## 组合优化" in note
    assert "## Reviewer 审查报告" in note
    assert "## Critic Agent 独立复核" in note


def test_optimize_portfolio_run_is_not_misclassified_as_cross_sectional_in_library(tmp_path: Path, monkeypatch):
    # Regression: config["universe"] = {"asset_class": ...} was being used to
    # carry asset_class for portfolio runs, but library/record.py treats any
    # run with a truthy config["universe"] as a cross-sectional backtest -
    # that faked field silently mislabeled every portfolio run.
    from quantbench.artifact.store import ArtifactStore
    from quantbench.agent.coordinator import Coordinator
    from quantbench.library.record import build_record

    store = ArtifactStore(tmp_path / "runs")
    run_a = _make_constituent_run(
        store, monkeypatch, _sample_ohlcv(seed=7), "def compute(df):\n    return df['close'].pct_change(5).fillna(0.0)\n", "factor a"
    )
    run_b = _make_constituent_run(
        store, monkeypatch, _sample_ohlcv(seed=8), "def compute(df):\n    return df['close'].pct_change(10).fillna(0.0)\n", "factor b"
    )
    portfolio = Coordinator(run_store=store, critic_llm=JsonCriticLLM()).optimize_portfolio([run_a.run_id, run_b.run_id])

    record = build_record(portfolio.run_id)
    assert record.cross_sectional is False
    assert record.asset_class == "equity"


def test_optimize_portfolio_tool_call_records_parent_run_id(tmp_path: Path, monkeypatch):
    from quantbench.artifact.store import ArtifactStore
    from quantbench.agent.coordinator import Coordinator

    store = ArtifactStore(tmp_path / "runs")
    run_a = _make_constituent_run(
        store, monkeypatch, _sample_ohlcv(seed=3), "def compute(df):\n    return df['close'].pct_change(5).fillna(0.0)\n", "factor a"
    )
    run_b = _make_constituent_run(
        store, monkeypatch, _sample_ohlcv(seed=4), "def compute(df):\n    return df['close'].pct_change(15).fillna(0.0)\n", "factor b"
    )

    script = [
        ("tools", [("optimize_portfolio", {"run_ids": [run_a.run_id, run_b.run_id], "method": "hrp"})]),
        ("text", "combined"),
    ]
    result = Coordinator(run_store=store, llm=FakeLLMClient(script), critic_llm=JsonCriticLLM()).run("组合这两个因子")

    conversation = json.loads((result.run_dir / "conversation.json").read_text(encoding="utf-8"))
    tool_result = next(
        json.loads(m["content"]) for m in conversation if m.get("role") == "tool"
    )
    child_manifest = json.loads((tmp_path / "runs" / tool_result["run_id"] / "manifest.json").read_text(encoding="utf-8"))
    assert child_manifest["parent_run_id"] == result.run_id
    assert tool_result["method"] == "hrp"


def _write_fake_constituent_run(store, series: pd.Series, asset_class: str | None, cross_sectional: bool = False) -> str:
    run = store.create_run(f"fake {asset_class}")
    key = "long_short_returns" if cross_sectional else "returns"
    payload = {
        "metrics": {"sharpe": 0.0},
        "series": {"timestamp": [str(ts) for ts in series.index], key: series.round(8).tolist()},
    }
    run.save_json("backtest_result.json", payload)
    config: dict = {"hypothesis": "fake"}
    if asset_class is None:
        pass  # no cache/universe info at all -> infer_asset_class() must return None, not guess.
    elif cross_sectional:
        config["universe"] = {"asset_class": asset_class}
    else:
        config["cache"] = {"provider": "ccxt_binance" if asset_class == "crypto" else "yfinance_equity"}
    run.save_config(config)
    run.finalize(data_hash="sha256:x", code_hash="sha256:x", metrics={"sharpe": 0.0})
    return run.run_id


def test_optimize_portfolio_rejects_mixed_asset_classes(tmp_path: Path):
    from quantbench.artifact.store import ArtifactStore
    from quantbench.agent.coordinator import Coordinator

    store = ArtifactStore(tmp_path / "runs")
    idx = _idx(120)
    equity_id = _write_fake_constituent_run(store, _series(np.random.normal(0, 0.01, 120), idx), "equity")
    crypto_id = _write_fake_constituent_run(store, _series(np.random.normal(0, 0.01, 120), idx), "crypto")

    with pytest.raises(ValueError, match="asset class"):
        Coordinator(run_store=store, critic_llm=JsonCriticLLM()).optimize_portfolio([equity_id, crypto_id])


def test_optimize_portfolio_rejects_when_one_constituent_has_unresolvable_asset_class(tmp_path: Path):
    # Regression: a run whose asset class can't be inferred must not be
    # silently dropped from the mismatch check. Before the fix, pairing an
    # unresolvable (e.g. legacy/config-less) run with a crypto run left
    # asset_classes = {"crypto"} (the unresolved run contributing nothing),
    # so the mismatch gate saw only one class and let equity-shaped data
    # through mixed with crypto data.
    from quantbench.artifact.store import ArtifactStore
    from quantbench.agent.coordinator import Coordinator

    store = ArtifactStore(tmp_path / "runs")
    idx = _idx(120)
    unknown_id = _write_fake_constituent_run(store, _series(np.random.normal(0, 0.01, 120), idx), None)
    crypto_id = _write_fake_constituent_run(store, _series(np.random.normal(0, 0.01, 120), idx), "crypto")

    with pytest.raises(ValueError, match="asset class"):
        Coordinator(run_store=store, critic_llm=JsonCriticLLM()).optimize_portfolio([unknown_id, crypto_id])


def test_optimize_portfolio_rejects_insufficient_overlap(tmp_path: Path):
    from quantbench.artifact.store import ArtifactStore
    from quantbench.agent.coordinator import Coordinator

    store = ArtifactStore(tmp_path / "runs")
    idx = _idx(10)
    run_a = _write_fake_constituent_run(store, _series(np.random.normal(0, 0.01, 10), idx), "equity")
    run_b = _write_fake_constituent_run(store, _series(np.random.normal(0, 0.01, 10), idx), "equity")

    with pytest.raises(ValueError, match="overlapping observations"):
        Coordinator(run_store=store, critic_llm=JsonCriticLLM()).optimize_portfolio([run_a, run_b])


def test_optimize_portfolio_critic_failure_degrades_gracefully(tmp_path: Path, monkeypatch):
    from quantbench.artifact.store import ArtifactStore
    from quantbench.agent.coordinator import Coordinator

    store = ArtifactStore(tmp_path / "runs")
    run_a = _make_constituent_run(
        store, monkeypatch, _sample_ohlcv(seed=5), "def compute(df):\n    return df['close'].pct_change(5).fillna(0.0)\n", "factor a"
    )
    run_b = _make_constituent_run(
        store, monkeypatch, _sample_ohlcv(seed=6), "def compute(df):\n    return df['close'].pct_change(20).fillna(0.0)\n", "factor b"
    )

    result = Coordinator(run_store=store, critic_llm=BrokenCriticLLM()).optimize_portfolio([run_a.run_id, run_b.run_id])

    critic = json.loads((result.run_dir / "critic_report.json").read_text(encoding="utf-8"))
    assert critic["status"] == "unavailable"
    manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["review"] is not None


def test_optimize_portfolio_flags_implausible_sharpe_from_near_perfect_hedge(tmp_path: Path):
    # A min-variance fit can find a near-perfect in-sample hedge between two
    # strongly anti-correlated constituents, driving realized variance to
    # near zero and mechanically producing an astronomical Sharpe even though
    # every input number is individually unremarkable - this must surface the
    # same sanity_check_metrics warning single-symbol/cross-sectional runs get.
    from quantbench.artifact.store import ArtifactStore
    from quantbench.agent.coordinator import Coordinator

    store = ArtifactStore(tmp_path / "runs")
    idx = _idx(200)
    rng = np.random.default_rng(42)
    a = rng.normal(0.002, 0.0003, 200)
    b = -a + rng.normal(0, 1e-7, 200)  # near-perfect negative correlation with a
    run_a = _write_fake_constituent_run(store, _series(a, idx), "equity")
    run_b = _write_fake_constituent_run(store, _series(b, idx), "equity")

    result = Coordinator(run_store=store, critic_llm=JsonCriticLLM()).optimize_portfolio(
        [run_a, run_b], method="min_variance"
    )

    assert abs(result.metrics["sharpe"]) > 10
    assert any("exceeds plausible range" in warning for warning in result.warnings)


def test_optimize_portfolio_rejects_out_of_range_run_id_count(tmp_path: Path):
    from quantbench.artifact.store import ArtifactStore
    from quantbench.agent.coordinator import Coordinator

    store = ArtifactStore(tmp_path / "runs")
    with pytest.raises(ValueError, match="run_ids"):
        Coordinator(run_store=store, critic_llm=JsonCriticLLM()).optimize_portfolio(["only_one"])


def test_cli_portfolio_optimize_does_not_swallow_option_values_as_run_ids(monkeypatch):
    # Regression test: --method takes a space-separated value ("--method
    # min_variance"), unlike _compare's only flag (--json-output, no value) -
    # a naive "not startswith('--')" filter would misparse the value token as
    # a spurious extra run_id.
    from click.testing import CliRunner
    from quantbench.cli import main

    captured = {}

    class FakeCoordinator:
        def __init__(self):
            pass

        def optimize_portfolio(self, run_ids, method=None, cost_bps=None, split=None, max_weight=None):
            captured["run_ids"] = run_ids
            captured["method"] = method
            captured["cost_bps"] = cost_bps
            return SimpleNamespace(run_id="run_x", metrics={}, warnings=[], run_dir=Path("."))

    monkeypatch.setattr("quantbench.cli.Coordinator", FakeCoordinator)

    result = CliRunner().invoke(
        main, ["portfolio", "optimize", "run_a", "run_b", "--method", "min_variance", "--cost-bps", "10"], catch_exceptions=False
    )
    assert result.exit_code == 0
    assert captured["run_ids"] == ["run_a", "run_b"]
    assert captured["method"] == "min_variance"
    assert captured["cost_bps"] == 10.0

    result = CliRunner().invoke(main, ["portfolio", "optimize", "run_a", "run_b", "--method=hrp"], catch_exceptions=False)
    assert captured["run_ids"] == ["run_a", "run_b"]
    assert captured["method"] == "hrp"
