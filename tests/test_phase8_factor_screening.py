import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from _fakes import FakeLLMClient


def _panel() -> pd.DataFrame:
    timestamps = pd.date_range("2024-01-01", periods=8, freq="1D", tz="UTC")
    rows = []
    specs = {
        "WIN": [100, 101, 103, 106, 110, 115, 121, 128],
        "MID": [100, 100, 101, 102, 103, 104, 105, 106],
        "LOS": [100, 99, 97, 94, 90, 85, 79, 72],
    }
    for symbol, closes in specs.items():
        for timestamp, close in zip(timestamps, closes, strict=True):
            rows.append(
                {
                    "symbol": symbol,
                    "timestamp": timestamp,
                    "open": close,
                    "high": close + 1,
                    "low": close - 1,
                    "close": close,
                    "volume": 1000,
                }
            )
    return pd.DataFrame(rows)


class JsonCriticLLM:
    def chat(self, messages, tools=None):
        payload = {
            "verdict": "PROMISING",
            "agrees_with_deterministic_verdict": True,
            "critique": "screened child reviewed",
            "narrative_consistency_issues": [],
            "recommended_next_steps": [],
        }
        message = SimpleNamespace(role="assistant", content=json.dumps(payload), tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _patch_universe_and_panel(monkeypatch, panel: pd.DataFrame) -> None:
    from quantbench.data.universe import UniverseDefinition

    monkeypatch.setattr(
        "quantbench.agent.coordinator.build_universe",
        lambda universe_name, as_of_date, point_in_time=False, limit=None: UniverseDefinition(
            name="tiny",
            as_of_date=as_of_date,
            symbols=["WIN", "MID", "LOS"],
            point_in_time=False,
            survivorship_bias_note="test",
            source="unit-test",
        ),
    )
    monkeypatch.setattr(
        "quantbench.agent.coordinator.fetch_universe_ohlcv",
        lambda universe, timeframe, start, end: (
            panel,
            {"symbols_requested": 3, "symbols_fetched": 3, "cache_hits": 0, "failed": {}, "sources": {"unit": 3}},
        ),
    )


def test_screen_factors_creates_child_runs_parent_links_and_sorted_summary(tmp_path: Path, monkeypatch):
    from quantbench.agent.coordinator import Coordinator
    from quantbench.artifact.store import ArtifactStore

    _patch_universe_and_panel(monkeypatch, _panel())
    candidates = [
        {"name": "bad", "code": "def compute(df):\n    return -df['close'].pct_change(1).fillna(0.0)\n"},
        {"name": "good", "code": "def compute(df):\n    return df['close'].pct_change(1).fillna(0.0)\n"},
    ]
    script = [
        ("tools", [("build_universe", {"universe_name": "sp500", "as_of_date": "2024-01-01", "limit": 3})]),
        (
            "tools",
            [
                (
                    "screen_factors",
                    {
                        "candidates": candidates,
                        "start": "2024-01-01",
                        "end": "2024-01-08",
                        "timeframe": "1d",
                        "n_groups": 3,
                        "cost_bps": 0,
                    },
                )
            ],
        ),
        ("text", "screen done"),
    ]

    result = Coordinator(
        run_store=ArtifactStore(tmp_path / "runs"),
        llm=FakeLLMClient(script),
        critic_llm=JsonCriticLLM(),
    ).run("批量筛选两个截面因子")

    summary = json.loads((result.run_dir / "factor_screen_summary.json").read_text(encoding="utf-8"))
    assert summary["critic_model"]
    assert [item["name"] for item in summary["candidates"]] == ["good", "bad"]
    child_ids = [item["run_id"] for item in summary["candidates"]]
    assert len(child_ids) == 2
    for child_id in child_ids:
        child_manifest = json.loads((tmp_path / "runs" / child_id / "manifest.json").read_text(encoding="utf-8"))
        assert child_manifest["parent_run_id"] == result.run_id
        assert child_manifest["critic_model"]
        assert child_manifest["critic"]["status"] == "ok"


def test_screen_factors_isolates_single_candidate_failure(tmp_path: Path, monkeypatch):
    from quantbench.agent.coordinator import Coordinator
    from quantbench.artifact.store import ArtifactStore

    _patch_universe_and_panel(monkeypatch, _panel())
    candidates = [
        {"name": "broken", "code": "def compute(df):\n    raise ValueError('bad factor')\n"},
        {"name": "good", "code": "def compute(df):\n    return df['close'].pct_change(1).fillna(0.0)\n"},
    ]
    script = [
        ("tools", [("build_universe", {"universe_name": "sp500", "as_of_date": "2024-01-01"})]),
        (
            "tools",
            [("screen_factors", {"candidates": candidates, "start": "2024-01-01", "end": "2024-01-08", "n_groups": 3})],
        ),
        ("text", "done"),
    ]

    result = Coordinator(
        run_store=ArtifactStore(tmp_path / "runs"),
        llm=FakeLLMClient(script),
        critic_llm=JsonCriticLLM(),
    ).run("批量筛选，允许单个失败")

    summary = json.loads((result.run_dir / "factor_screen_summary.json").read_text(encoding="utf-8"))
    statuses = {item["name"]: item["status"] for item in summary["candidates"]}
    assert statuses == {"good": "completed", "broken": "failed"}
    broken = next(item for item in summary["candidates"] if item["name"] == "broken")
    broken_dir = tmp_path / "runs" / broken["run_id"]
    assert (broken_dir / "error.json").exists()
    # Even though the candidate failed mid-backtest, its code and parent linkage
    # must still be recoverable - config.yaml is written before the risky calls.
    assert (broken_dir / "signal.py").exists()
    broken_config = (broken_dir / "config.yaml").read_text(encoding="utf-8")
    assert result.run_id in broken_config
    assert "broken" in broken_config


def test_screen_factors_requires_universe_and_candidate_limit(tmp_path: Path, monkeypatch):
    from quantbench.agent.coordinator import Coordinator
    from quantbench.artifact.store import ArtifactStore

    _patch_universe_and_panel(monkeypatch, _panel())
    too_many = [
        {"name": f"f{i}", "code": "def compute(df):\n    return df['close'].pct_change(1).fillna(0.0)\n"}
        for i in range(25)
    ]
    script = [
        (
            "tools",
            [
                (
                    "screen_factors",
                    {
                        "candidates": [{"name": "x", "code": "def compute(df):\n    return df['close']\n"}],
                        "start": "2024-01-01",
                        "end": "2024-01-08",
                    },
                )
            ],
        ),
        ("tools", [("build_universe", {"universe_name": "sp500", "as_of_date": "2024-01-01"})]),
        (
            "tools",
            [
                (
                    "screen_factors",
                    {
                        "candidates": too_many,
                        "start": "2024-01-01",
                        "end": "2024-01-08",
                    },
                )
            ],
        ),
        ("text", "done"),
    ]

    result = Coordinator(
        run_store=ArtifactStore(tmp_path / "runs"),
        llm=FakeLLMClient(script),
        critic_llm=JsonCriticLLM(),
    ).run("错误使用批量筛选")

    steps = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))["steps"]
    assert "no universe loaded" in steps[0]["result"]["error"]
    assert "between 1 and" in steps[2]["result"]["error"]


def test_backtest_tools_are_blocked_after_screen_factors_runs(tmp_path: Path, monkeypatch):
    """Regression for a real production run where the model called run_signal_backtest again
    after screen_factors already produced final results, silently redoing expensive work and
    (in that run) erroring out because no single-symbol data was ever fetched. The guard must
    reject any further backtest tool call for the rest of the session, not just rely on the
    system prompt telling the model not to."""
    from quantbench.agent.coordinator import Coordinator
    from quantbench.artifact.store import ArtifactStore

    _patch_universe_and_panel(monkeypatch, _panel())
    candidates = [{"name": "good", "code": "def compute(df):\n    return df['close'].pct_change(1).fillna(0.0)\n"}]
    script = [
        ("tools", [("build_universe", {"universe_name": "sp500", "as_of_date": "2024-01-01", "limit": 3})]),
        (
            "tools",
            [("screen_factors", {"candidates": candidates, "start": "2024-01-01", "end": "2024-01-08", "n_groups": 3})],
        ),
        ("tools", [("run_signal_backtest", {"code": candidates[0]["code"], "cost_bps": 5})]),
        (
            "tools",
            [
                (
                    "run_cross_sectional_backtest",
                    {"code": candidates[0]["code"], "start": "2024-01-01", "end": "2024-01-08", "n_groups": 3},
                )
            ],
        ),
        ("text", "done"),
    ]

    result = Coordinator(
        run_store=ArtifactStore(tmp_path / "runs"),
        llm=FakeLLMClient(script),
        critic_llm=JsonCriticLLM(),
    ).run("批量筛选后不应再单独跑回测")

    steps = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))["steps"]
    assert steps[1]["tool"] == "screen_factors"
    assert "already produced final" in steps[2]["result"]["error"]
    assert "already produced final" in steps[3]["result"]["error"]
