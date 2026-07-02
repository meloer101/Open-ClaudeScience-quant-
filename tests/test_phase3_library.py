import json
import shutil

import numpy as np
import pandas as pd
import pytest
import yaml
from click.testing import CliRunner


def _finding(check, severity, message="finding", detail=None):
    return {"check": check, "severity": severity, "message": message, "detail": detail or {}}


def _write_run(
    runs_dir,
    run_id,
    *,
    hypothesis="momentum test",
    data_path="/tmp/data_cache/yfinance_equity_AAPL_1d_2020_2021.parquet",
    universe=None,
    metrics=None,
    verdict="PROMISING",
    findings=None,
    parent_run_id=None,
    signal_code="def compute(df):\n    return df['close'].pct_change().fillna(0)\n",
):
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    metrics = metrics or {"sharpe": 1.2, "annual_return": 0.18, "max_drawdown": -0.12, "turnover_annual": 20.0}
    findings = findings or [
        _finding(
            "out_of_sample",
            "warning",
            "decay",
            {"test_metrics": {"sharpe": 0.7}, "train_metrics": {"sharpe": 1.1}, "sharpe_decay_ratio": 0.64},
        ),
        _finding("cost_sensitivity", "pass", "ok", {"sharpe_by_multiplier": {"1.0": 1.2, "2.0": 0.8}}),
    ]
    manifest = {
        "run_id": run_id,
        "user_request": hypothesis,
        "created_at": "2026-07-01T00:00:00+00:00",
        "summary": "done",
        "metrics": metrics,
        "warnings": ["review warning"] if any(f["severity"] == "warning" for f in findings) else [],
        "review": {"verdict": verdict, "verdict_reason": "reason", "findings": findings} if verdict else None,
        "data_hash": "sha256:data",
        "code_hash": "sha256:code",
        "parent_run_id": parent_run_id,
    }
    config = {
        "hypothesis": hypothesis,
        "data_path": data_path,
        "universe": universe,
        "date_range": {"start": "2020-01-01", "end": "2021-01-01"},
        "timeframe": "1d",
        "parent_run_id": parent_run_id,
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "config.yaml").write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    (run_dir / "signal.py").write_text(signal_code, encoding="utf-8")
    return run_dir


@pytest.fixture
def patched_runs(tmp_path, monkeypatch):
    monkeypatch.setattr("quantbench.api.run_reader.RUNS_DIR", tmp_path)
    return tmp_path


def _write_ohlcv_parquet(path, rows=320, seed=0):
    """A single-symbol OHLCV frame the vectorized backtest can run on."""
    rng = np.random.default_rng(seed)
    timestamps = pd.date_range("2020-01-01", periods=rows, freq="D", tz="UTC")
    close = 100 + np.cumsum(rng.normal(0, 1, rows))
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": rng.uniform(1e6, 2e6, rows),
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path)
    return path


def test_build_record_extracts_review_metrics_and_conservative_classification(patched_runs):
    from quantbench.library.record import build_record

    _write_run(
        patched_runs,
        "run_20260701_000000_aaaa",
        hypothesis="RSI 反转 因子",
        data_path="/tmp/data_cache/yfinance_equity_AAPL_1d_2020_2021.parquet",
        metrics={"sharpe": 1.4, "annual_return": 0.2, "max_drawdown": -0.1, "turnover_annual": 12.0, "ic_mean": 0.03},
    )

    record = build_record("run_20260701_000000_aaaa")

    assert record.run_id == "run_20260701_000000_aaaa"
    assert record.asset_class == "equity"
    assert record.factor_family == "reversal"
    assert record.sharpe == 1.4
    assert record.oos_sharpe == 0.7
    assert record.verdict == "PROMISING"
    assert record.warning_count == 1
    assert record.critical_count == 0


def test_build_record_keeps_missing_metrics_as_none_and_indexes_failed_runs(patched_runs):
    from quantbench.library.record import build_record

    run_dir = patched_runs / "run_20260701_010000_fail"
    run_dir.mkdir()
    (run_dir / "request.txt").write_text("broken value idea", encoding="utf-8")
    (run_dir / "error.json").write_text(json.dumps({"traceback": "ValueError: bad data"}), encoding="utf-8")

    record = build_record("run_20260701_010000_fail")

    assert record.status == "failed"
    assert record.hypothesis == "broken value idea"
    assert record.sharpe is None
    assert record.verdict is None
    assert record.error_summary == "ValueError: bad data"


def test_index_filter_sort_and_rebuild_tracks_filesystem(patched_runs):
    from quantbench.library.index import ExperimentIndex

    _write_run(patched_runs, "run_20260701_000000_a", hypothesis="momentum", metrics={"sharpe": 0.3})
    _write_run(
        patched_runs,
        "run_20260701_000001_b",
        hypothesis="momentum BTC",
        data_path="/tmp/data_cache/ccxt_binance_BTC_USDT_4h.parquet",
        metrics={"sharpe": 1.8},
        verdict="STRONG",
        findings=[],
    )

    records = ExperimentIndex.build().filter(verdicts={"STRONG"}, asset_class="crypto").sort("sharpe").records

    assert [record.run_id for record in records] == ["run_20260701_000001_b"]

    shutil.rmtree(patched_runs / "run_20260701_000001_b")
    rebuilt = ExperimentIndex.build()

    assert [record.run_id for record in rebuilt.records] == ["run_20260701_000000_a"]


def test_compare_runs_aligns_metrics_verdicts_and_findings(patched_runs):
    from quantbench.library.compare import compare_runs

    _write_run(patched_runs, "run_20260701_000000_a", metrics={"sharpe": 1.0, "annual_return": 0.1})
    _write_run(
        patched_runs,
        "run_20260701_000001_b",
        metrics={"sharpe": 1.5, "annual_return": 0.2},
        findings=[_finding("lookahead", "critical", "future shift")],
        verdict="REJECTED",
    )

    table = compare_runs(["run_20260701_000000_a", "run_20260701_000001_b"])

    assert table["metrics"]["sharpe"] == {"run_20260701_000000_a": 1.0, "run_20260701_000001_b": 1.5}
    assert table["verdicts"]["run_20260701_000001_b"] == "REJECTED"
    assert table["findings"]["run_20260701_000001_b"][0]["check"] == "lookahead"


def test_lineage_returns_ordered_chain_signal_diff_and_metric_delta(patched_runs):
    from quantbench.library.lineage import lineage

    _write_run(patched_runs, "run_20260701_000000_a", metrics={"sharpe": 1.0}, signal_code="def compute(df):\n    return df.close\n")
    _write_run(
        patched_runs,
        "run_20260701_000001_b",
        parent_run_id="run_20260701_000000_a",
        metrics={"sharpe": 1.4},
        signal_code="def compute(df):\n    return df.close.rolling(20).mean()\n",
    )
    _write_run(
        patched_runs,
        "run_20260701_000002_c",
        parent_run_id="run_20260701_000001_b",
        metrics={"sharpe": 1.1},
        signal_code="def compute(df):\n    return df.close.rolling(60).mean()\n",
    )

    tree = lineage("run_20260701_000002_c")

    assert [node["run_id"] for node in tree["chain"]] == [
        "run_20260701_000000_a",
        "run_20260701_000001_b",
        "run_20260701_000002_c",
    ]
    assert tree["edges"][0]["metric_delta"]["sharpe"] == pytest.approx(0.4)
    assert "-    return df.close" in tree["edges"][0]["signal_diff"]
    assert "+    return df.close.rolling(20).mean()" in tree["edges"][0]["signal_diff"]


def test_aggregate_summary_uses_code_calculated_numbers_and_marks_small_samples(patched_runs):
    from quantbench.library.aggregate import summarize
    from quantbench.library.index import ExperimentIndex

    _write_run(patched_runs, "run_20260701_000000_a", hypothesis="momentum AAPL", metrics={"sharpe": 1.0})
    _write_run(
        patched_runs,
        "run_20260701_000001_b",
        hypothesis="momentum MSFT",
        data_path="/tmp/data_cache/yfinance_equity_MSFT_1d.parquet",
        metrics={"sharpe": 2.0},
        verdict="STRONG",
        findings=[],
    )
    _write_run(
        patched_runs,
        "run_20260701_000002_c",
        hypothesis="value AAPL",
        metrics={"sharpe": 0.5},
        verdict="WEAK",
        findings=[_finding("cost_sensitivity", "warning", "costly")],
    )

    rows = summarize(ExperimentIndex.build(), by=("factor_family", "asset_class"))
    by_family = {row["factor_family"]: row for row in rows}

    assert by_family["momentum"]["count"] == 2
    assert by_family["momentum"]["sharpe_mean"] == pytest.approx(1.5)
    assert by_family["momentum"]["verdict_counts"] == {"PROMISING": 1, "STRONG": 1}
    assert by_family["momentum"]["sample_warning"] is False
    assert by_family["value"]["cost_sensitive_count"] == 1
    assert by_family["value"]["sample_warning"] is True


def test_build_fork_config_inherits_parent_inputs_and_signal(patched_runs):
    from quantbench.library.fork import build_fork_config

    _write_run(
        patched_runs,
        "run_20260701_000000_a",
        hypothesis="momentum parent",
        data_path="/tmp/data_cache/yfinance_equity_AAPL_1d_2020_2021.parquet",
        signal_code="def compute(df):\n    return df.close.pct_change()\n",
    )

    config = build_fork_config("run_20260701_000000_a", "把窗口从20日改成60日")

    assert config["parent_run_id"] == "run_20260701_000000_a"
    assert config["data_path"] == "/tmp/data_cache/yfinance_equity_AAPL_1d_2020_2021.parquet"
    assert config["date_range"] == {"start": "2020-01-01", "end": "2021-01-01"}
    assert "pct_change" in config["parent_signal_code"]
    assert config["modification_request"] == "把窗口从20日改成60日"


def test_cli_library_list_and_compare(patched_runs, monkeypatch):
    monkeypatch.setattr("quantbench.agent.coordinator.RUNS_DIR", patched_runs)
    _write_run(patched_runs, "run_20260701_000000_a", hypothesis="momentum AAPL", metrics={"sharpe": 1.0})
    _write_run(patched_runs, "run_20260701_000001_b", hypothesis="value AAPL", metrics={"sharpe": 0.2}, verdict="WEAK")

    from quantbench.cli import main

    list_result = CliRunner().invoke(main, ["library", "list", "--verdict", "PROMISING,STRONG", "--sort", "sharpe"])
    assert list_result.exit_code == 0, list_result.output
    assert "run_20260701_000000_a" in list_result.output
    assert "run_20260701_000001_b" not in list_result.output

    compare_result = CliRunner().invoke(main, ["compare", "run_20260701_000000_a", "run_20260701_000001_b"])
    assert compare_result.exit_code == 0, compare_result.output
    assert "sharpe" in compare_result.output
    assert "PROMISING" in compare_result.output


def test_coordinator_library_question_injects_deterministic_summary(patched_runs, monkeypatch):
    from _fakes import FakeLLMClient

    monkeypatch.setattr("quantbench.agent.coordinator.RUNS_DIR", patched_runs)
    _write_run(patched_runs, "run_20260701_000000_a", hypothesis="momentum AAPL", metrics={"sharpe": 1.0})
    _write_run(
        patched_runs,
        "run_20260701_000001_b",
        hypothesis="momentum MSFT",
        data_path="/tmp/data_cache/yfinance_equity_MSFT_1d.parquet",
        metrics={"sharpe": 2.0},
        verdict="STRONG",
        findings=[],
    )
    fake = FakeLLMClient([("text", "momentum 在 equity 上样本数 2，平均 Sharpe 1.5。")])

    from quantbench.agent.coordinator import Coordinator
    from quantbench.artifact.store import ArtifactStore

    result = Coordinator(run_store=ArtifactStore(patched_runs), llm=fake).run("在我做过的所有实验里，哪一类因子在美股上最有希望？")

    assert "平均 Sharpe 1.5" in result.summary
    injected_prompt = fake.calls[0][0][1]["content"]
    assert '"factor_family": "momentum"' in injected_prompt
    assert '"count": 2' in injected_prompt
    assert '"sharpe_mean": 1.5' in injected_prompt
    assert fake.calls[0][1] == []


def test_is_library_question_routing_is_conservative():
    from quantbench.agent.coordinator import _is_library_question

    # Real cross-run library questions are routed to the library-answer path.
    assert _is_library_question("在我做过的所有实验里，哪一类因子在美股上最有希望？")
    assert _is_library_question("Across runs, which factor family is most promising?")
    assert _is_library_question("summarize my past experiments")

    # Ordinary backtest requests must NOT be misrouted - "run"/"best"/"which"
    # are common in these and previously triggered a false positive that
    # silently skipped the backtest.
    assert not _is_library_question("run a backtest to find the best momentum factor")
    assert not _is_library_question("测试20日动量因子在AAPL上的表现，2018-01-01到2024-01-01")
    assert not _is_library_question("which timeframe gives the strongest RSI reversal on BTC")


def test_execute_fork_records_parent_and_preserves_data_hash(patched_runs, monkeypatch):
    from _fakes import FakeLLMClient

    from quantbench.agent.coordinator import Coordinator
    from quantbench.artifact.store import ArtifactStore
    from quantbench.data.cache import file_sha256

    monkeypatch.setattr("quantbench.agent.coordinator.RUNS_DIR", patched_runs)

    parquet = _write_ohlcv_parquet(patched_runs / "data_cache" / "yfinance_equity_AAPL_1d.parquet")
    real_hash = f"sha256:{file_sha256(parquet)}"

    _write_run(
        patched_runs,
        "run_20260701_000000_a",
        hypothesis="momentum parent",
        data_path=str(parquet),
        signal_code="def compute(df):\n    return df['close'].rolling(20).mean() - df['close']\n",
    )
    # Align the parent manifest's data_hash with the real file so the fork's
    # drift guard has a meaningful value to compare against.
    parent_manifest_path = patched_runs / "run_20260701_000000_a" / "manifest.json"
    parent_manifest = json.loads(parent_manifest_path.read_text())
    parent_manifest["data_hash"] = real_hash
    parent_manifest_path.write_text(json.dumps(parent_manifest), encoding="utf-8")

    child_code = "def compute(df):\n    return df['close'].rolling(60).mean() - df['close']\n"
    fake = FakeLLMClient([("tools", [("run_signal_backtest", {"code": child_code})]), ("text", "fork done")])

    coordinator = Coordinator(run_store=ArtifactStore(patched_runs), llm=fake)
    result = coordinator.run_fork("run_20260701_000000_a", "把回看窗口从20日改成60日")

    from quantbench.api import run_reader

    manifest = run_reader.read_manifest(result.run_id)
    config = run_reader.read_config(result.run_id)

    assert manifest["parent_run_id"] == "run_20260701_000000_a"
    assert config["parent_run_id"] == "run_20260701_000000_a"
    # Data was inherited untouched, so the child hash must equal the parent's
    # and no drift warning should be raised.
    assert manifest["data_hash"] == real_hash
    assert not any("data drift" in warning.lower() for warning in manifest["warnings"])
    # The child only changed the signal.
    assert "rolling(60)" in (patched_runs / result.run_id / "signal.py").read_text()
    # Review ran and the research note carries a lineage section.
    assert (patched_runs / result.run_id / "review_report.json").exists()
    assert "## 谱系" in (patched_runs / result.run_id / "research_note.md").read_text()


def test_fork_rejects_cross_sectional_parent(patched_runs, monkeypatch):
    from _fakes import FakeLLMClient

    from quantbench.agent.coordinator import Coordinator
    from quantbench.artifact.store import ArtifactStore

    monkeypatch.setattr("quantbench.agent.coordinator.RUNS_DIR", patched_runs)
    _write_run(
        patched_runs,
        "run_20260701_000000_x",
        hypothesis="cross sectional momentum",
        universe={"provider": "sp500", "symbols": ["AAPL", "MSFT"]},
    )

    coordinator = Coordinator(run_store=ArtifactStore(patched_runs), llm=FakeLLMClient([("text", "unused")]))

    with pytest.raises(ValueError, match="cross-sectional"):
        coordinator.run_fork("run_20260701_000000_x", "换个信号")
