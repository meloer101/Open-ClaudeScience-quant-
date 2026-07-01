import json

from click.testing import CliRunner

from _fakes import FakeLLMClient


def test_cli_generates_phase0_artifacts(tmp_path, monkeypatch):
    """Drives the real CLI entrypoint end-to-end, with the LLM call replaced by
    a scripted fake so this test doesn't need network access or an API key."""
    monkeypatch.setattr("quantbench.agent.coordinator.RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr("quantbench.data.cache.DATA_CACHE_DIR", tmp_path / "data_cache")

    signal_code = (
        "def compute(df):\n"
        "    return df['close'].pct_change().fillna(0.0)\n"
    )
    script = [
        (
            "tools",
            [("fetch_ohlcv", {"symbol": "BTC/USDT", "timeframe": "4h", "start": "2023-01-01", "end": "2023-03-01"})],
        ),
        ("tools", [("run_signal_backtest", {"code": signal_code, "cost_bps": 5})]),
        ("text", "Backtest complete; treat as preliminary, Phase 0 has no reviewer yet."),
    ]
    monkeypatch.setattr("quantbench.agent.coordinator.LLMClient", lambda model: FakeLLMClient(script))

    from quantbench.cli import main

    result = CliRunner().invoke(
        main, ["测试一个简单动量信号在 BTC/USDT 4h 上的表现，2023-01-01 到 2023-03-01"]
    )

    assert result.exit_code == 0, result.output
    assert "Artifact directory:" in result.output

    run_dirs = list((tmp_path / "runs").glob("run_*"))
    assert len(run_dirs) == 1
    names = {path.name for path in run_dirs[0].iterdir()}
    assert {
        "config.yaml",
        "signal.py",
        "backtest_result.json",
        "equity_curve.png",
        "drawdown.png",
        "research_note.md",
        "manifest.json",
    }.issubset(names)

    manifest = json.loads((run_dirs[0] / "manifest.json").read_text(encoding="utf-8"))
    assert [step["tool"] for step in manifest["steps"]] == ["fetch_ohlcv", "run_signal_backtest"]
