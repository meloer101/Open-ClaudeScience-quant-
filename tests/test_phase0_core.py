import json
from pathlib import Path

import numpy as np
import pandas as pd

from _fakes import FakeLLMClient


def sample_ohlcv(rows: int = 80) -> pd.DataFrame:
    timestamp = pd.date_range("2023-01-01", periods=rows, freq="4h", tz="UTC")
    trend = np.linspace(100, 130, rows)
    cycle = np.sin(np.linspace(0, 10, rows)) * 4
    close = trend + cycle
    return pd.DataFrame(
        {
            "timestamp": timestamp,
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.linspace(1000, 2000, rows),
        }
    )


def test_backtest_captures_correct_sign_at_signal_transition():
    """Regression test for the off-by-one alignment bug: a signal that correctly
    turns long one bar *before* a price jump (using only causally-available data)
    must show a gain at that jump, not a loss."""
    from quantbench.engine.vectorized_backtest import run_vectorized_backtest

    n = 40
    close = pd.Series([100.0] * 24 + [120.0] * 16)  # jump happens between bar 23 and 24
    timestamp = pd.date_range("2023-01-01", periods=n, freq="4h", tz="UTC")
    df = pd.DataFrame(
        {"timestamp": timestamp, "open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 1.0}
    )
    # signal reads "low" (long trigger) starting at bar 23, i.e. known at bar 23's
    # close, strictly before the price actually jumps between bar 23 and 24.
    raw_signal = pd.Series([0.5] * 23 + [-0.9] * 17)

    result = run_vectorized_backtest(df, raw_signal, cost_bps=0)
    jump_return = result.returns.iloc[23]
    assert jump_return > 0, (
        f"expected a gain when a causally-valid long signal precedes a price jump, got {jump_return}"
    )


def test_vectorized_backtest_returns_metrics_and_curves():
    from quantbench.engine.vectorized_backtest import run_vectorized_backtest

    df = sample_ohlcv(160)
    close = df["close"].astype(float)
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rsi = 100 - (100 / (1 + avg_gain / avg_loss.replace(0, np.nan)))
    signal = (-(rsi - 50) / 50).clip(-1, 1).fillna(0.0)

    result = run_vectorized_backtest(df, signal, cost_bps=5)

    assert set(result.metrics) >= {
        "sharpe",
        "annual_return",
        "max_drawdown",
        "turnover_annual",
        "ic_mean",
    }
    assert len(result.equity_curve) == len(df)
    assert len(result.drawdown) == len(df)

    # Phase 4: the single-symbol path used to only persist turnover_annual
    # (a scalar), which meant the Web UI had no way to render a turnover
    # chart for single-symbol runs even though the per-period series was
    # already computed in-memory. It must now round-trip through
    # to_json_dict() the same way the cross-sectional path already does.
    payload = result.to_json_dict()
    assert len(payload["series"]["turnover"]) == len(df)
    assert all(value >= 0 for value in payload["series"]["turnover"])


def test_fetch_ohlcv_marks_synthetic_fallback_and_persists_across_cache_hits(tmp_path, monkeypatch):
    from quantbench.data import exchange
    from quantbench.data.providers import ccxt_perpetual

    monkeypatch.setattr("quantbench.data.cache.DATA_CACHE_DIR", tmp_path)

    def boom(*args, **kwargs):
        raise RuntimeError("network blocked")

    monkeypatch.setattr(ccxt_perpetual, "download_ohlcv", boom)

    _, _, meta_first = exchange.fetch_ohlcv("BTC/USDT", "4h", "2023-01-01", "2023-01-05")
    assert meta_first["source"] == "deterministic_synthetic_fallback"
    assert meta_first["cache_hit"] is False

    _, _, meta_cached = exchange.fetch_ohlcv("BTC/USDT", "4h", "2023-01-01", "2023-01-05")
    assert meta_cached["cache_hit"] is True
    assert meta_cached["source"] == "deterministic_synthetic_fallback"


def test_sanity_check_flags_implausible_metrics():
    from quantbench.engine.metrics import sanity_check_metrics

    warnings = sanity_check_metrics({"sharpe": 32.98, "annual_return": 72.07})
    assert any("Sharpe" in w for w in warnings)
    assert any("return" in w for w in warnings)

    assert sanity_check_metrics({"sharpe": 1.1, "annual_return": 0.18}) == []


def test_artifact_store_writes_phase0_files(tmp_path: Path):
    from quantbench.artifact.store import ArtifactStore

    store = ArtifactStore(tmp_path)
    run = store.create_run("测试 RSI")
    run.save_config({"symbol": "BTC/USDT"})
    run.save_code("signal.py", "print('ok')\n")
    run.save_json("backtest_result.json", {"metrics": {"sharpe": 1.0}})
    run.save_text("research_note.md", "# Research Note\n")
    run.finalize(data_hash="sha256:data", code_hash="sha256:code")

    expected = {
        "config.yaml",
        "signal.py",
        "backtest_result.json",
        "research_note.md",
        "manifest.json",
    }
    assert expected.issubset({path.name for path in run.run_dir.iterdir()})


def test_coordinator_runs_full_tool_loop_with_fake_llm(tmp_path, monkeypatch):
    from quantbench.agent.coordinator import Coordinator
    from quantbench.artifact.store import ArtifactStore

    monkeypatch.setattr("quantbench.data.cache.DATA_CACHE_DIR", tmp_path / "data_cache")

    signal_code = (
        "def compute(df):\n"
        "    return df['close'].pct_change().fillna(0.0)\n"
    )
    script = [
        ("tools", [("fetch_ohlcv", {"symbol": "BTC/USDT", "timeframe": "4h", "start": "2023-01-01", "end": "2023-03-01"})]),
        ("tools", [("run_signal_backtest", {"code": signal_code, "cost_bps": 5})]),
        ("text", "Backtest complete; treat as preliminary, Phase 0 has no reviewer yet."),
    ]
    fake_llm = FakeLLMClient(script)
    coordinator = Coordinator(run_store=ArtifactStore(tmp_path / "runs"), llm=fake_llm)

    result = coordinator.run("测试一个简单动量信号在 BTC/USDT 4h 上的表现")

    assert result.metrics  # the backtest tool actually ran and returned metrics
    assert "def compute(df):" in (result.run_dir / "signal.py").read_text()
    assert (result.run_dir / "backtest_result.json").exists()
    assert (result.run_dir / "equity_curve.png").exists()
    assert (result.run_dir / "drawdown.png").exists()
    assert (result.run_dir / "conversation.json").exists()
    assert "preliminary" in result.summary

    manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
    tool_names = [step["tool"] for step in manifest["steps"]]
    assert tool_names == ["fetch_ohlcv", "run_signal_backtest"]
    assert manifest["conversation_log"] == "conversation.json"
    conversation = json.loads((result.run_dir / "conversation.json").read_text(encoding="utf-8"))
    assert conversation[-1]["content"] == result.summary


def test_signal_py_is_independently_reproducible(tmp_path, monkeypatch):
    """Regression test for the PHASE0.md acceptance criterion: pull signal.py out
    of a run directory and it must run standalone and reproduce the same values."""
    import subprocess
    import sys

    from quantbench.agent.coordinator import Coordinator
    from quantbench.artifact.store import ArtifactStore

    monkeypatch.setattr("quantbench.data.cache.DATA_CACHE_DIR", tmp_path / "data_cache")

    signal_code = (
        "def compute(df):\n"
        "    return df['close'].pct_change(3).fillna(0.0)\n"
    )
    script = [
        ("tools", [("fetch_ohlcv", {"symbol": "BTC/USDT", "timeframe": "4h", "start": "2023-01-01", "end": "2023-02-01"})]),
        ("tools", [("run_signal_backtest", {"code": signal_code, "cost_bps": 5})]),
        ("text", "done"),
    ]
    coordinator = Coordinator(run_store=ArtifactStore(tmp_path / "runs"), llm=FakeLLMClient(script))
    result = coordinator.run("测试一个简单动量信号")

    import yaml

    config = yaml.safe_load((result.run_dir / "config.yaml").read_text(encoding="utf-8"))
    output_csv = tmp_path / "standalone_output.csv"
    completed = subprocess.run(
        [sys.executable, str(result.run_dir / "signal.py"), config["data_path"], "--output", str(output_csv)],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert output_csv.exists()
    assert output_csv.read_text(encoding="utf-8").startswith("timestamp,signal")


def test_coordinator_reports_tool_error_without_crashing(tmp_path, monkeypatch):
    from quantbench.agent.coordinator import Coordinator
    from quantbench.artifact.store import ArtifactStore

    monkeypatch.setattr("quantbench.data.cache.DATA_CACHE_DIR", tmp_path / "data_cache")

    script = [
        ("tools", [("run_signal_backtest", {"code": "def compute(df):\n    return df['close']", "cost_bps": 5})]),
        ("text", "No data was available, so no backtest could run."),
    ]
    coordinator = Coordinator(run_store=ArtifactStore(tmp_path / "runs"), llm=FakeLLMClient(script))

    result = coordinator.run("测试信号但故意不先拉数据")

    manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["steps"][0]["result"] == {"error": "no market data loaded yet - call fetch_ohlcv first"}
    assert result.metrics == {}
