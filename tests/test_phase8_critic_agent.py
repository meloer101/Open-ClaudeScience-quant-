import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

from _fakes import FakeLLMClient


def _sample_ohlcv(rows: int = 180) -> pd.DataFrame:
    timestamp = pd.date_range("2022-01-01", periods=rows, freq="1D", tz="UTC")
    close = 100 + np.linspace(0, 25, rows) + np.sin(np.linspace(0, 18, rows)) * 2
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


def _script(signal_code: str):
    return [
        ("tools", [("fetch_ohlcv", {"symbol": "AAPL", "timeframe": "1d", "start": "2022-01-01", "end": "2022-06-30"})]),
        ("tools", [("run_signal_backtest", {"code": signal_code, "cost_bps": 5})]),
        ("text", "Coordinator summary with the actual metrics."),
    ]


class JsonCriticLLM:
    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = []

    def chat(self, messages, tools=None):
        self.calls.append((messages, tools))
        message = SimpleNamespace(role="assistant", content=json.dumps(self.payload), tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class BrokenCriticLLM:
    def chat(self, messages, tools=None):
        raise RuntimeError("critic unavailable")


def _patch_fetch(tmp_path: Path, monkeypatch, df: pd.DataFrame) -> None:
    data_path = tmp_path / "data.parquet"
    df.to_parquet(data_path, index=False)

    def fake_fetch_ohlcv(symbol, timeframe, start, end):
        return data_path, df, {"source": "unit-test", "cache_hit": False}

    monkeypatch.setattr("quantbench.agent.coordinator.fetch_ohlcv", fake_fetch_ohlcv)


def test_critic_report_is_written_to_artifacts_manifest_and_note(tmp_path: Path, monkeypatch):
    from quantbench.agent.coordinator import Coordinator
    from quantbench.artifact.store import ArtifactStore

    _patch_fetch(tmp_path, monkeypatch, _sample_ohlcv())
    signal_code = "def compute(df):\n    return df['close'].pct_change(20).fillna(0.0)\n"
    critic_payload = {
        "verdict": "PROMISING",
        "agrees_with_deterministic_verdict": True,
        "critique": "The summary is consistent with the deterministic evidence.",
        "narrative_consistency_issues": [],
        "recommended_next_steps": ["Run a longer out-of-sample test."],
    }

    coordinator = Coordinator(
        run_store=ArtifactStore(tmp_path / "runs"),
        llm=FakeLLMClient(_script(signal_code)),
        critic_llm=JsonCriticLLM(critic_payload),
    )
    result = coordinator.run("测试20日动量因子")

    critic = json.loads((result.run_dir / "critic_report.json").read_text(encoding="utf-8"))
    assert critic["status"] == "ok"
    assert critic["verdict"] == "PROMISING"
    manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["critic"]["verdict"] == "PROMISING"
    assert manifest["critic_model"]
    note = (result.run_dir / "research_note.md").read_text(encoding="utf-8")
    assert "## Critic Agent 独立复核" in note
    assert "The summary is consistent" in note


def test_critic_disagreement_adds_warning_without_overriding_reviewer_verdict(tmp_path: Path, monkeypatch):
    from quantbench.agent.coordinator import Coordinator
    from quantbench.artifact.store import ArtifactStore

    _patch_fetch(tmp_path, monkeypatch, _sample_ohlcv())
    signal_code = "def compute(df):\n    return df['close'].shift(-1).fillna(df['close'])\n"
    critic_payload = {
        "verdict": "REJECTED",
        "agrees_with_deterministic_verdict": False,
        "critique": "The narrative understates a lookahead issue.",
        "narrative_consistency_issues": ["Lookahead warning is not emphasized."],
        "recommended_next_steps": ["Rewrite the factor causally."],
    }

    coordinator = Coordinator(
        run_store=ArtifactStore(tmp_path / "runs"),
        llm=FakeLLMClient(_script(signal_code)),
        critic_llm=JsonCriticLLM(critic_payload),
    )
    result = coordinator.run("测试一个坏因子")

    manifest = json.loads((result.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["review"]["verdict"] == "REJECTED"
    assert manifest["critic"]["verdict"] == "REJECTED"
    assert any("Critic Agent" in warning and "不一致" in warning for warning in manifest["warnings"])


def test_critic_failure_degrades_to_unavailable_and_run_still_finalizes(tmp_path: Path, monkeypatch):
    from quantbench.agent.coordinator import Coordinator
    from quantbench.artifact.store import ArtifactStore

    _patch_fetch(tmp_path, monkeypatch, _sample_ohlcv())
    signal_code = "def compute(df):\n    return df['close'].pct_change(5).fillna(0.0)\n"

    coordinator = Coordinator(
        run_store=ArtifactStore(tmp_path / "runs"),
        llm=FakeLLMClient(_script(signal_code)),
        critic_llm=BrokenCriticLLM(),
    )
    result = coordinator.run("测试 Critic 降级")

    assert (result.run_dir / "manifest.json").exists()
    critic = json.loads((result.run_dir / "critic_report.json").read_text(encoding="utf-8"))
    assert critic["status"] == "unavailable"
    note = (result.run_dir / "research_note.md").read_text(encoding="utf-8")
    assert "Critic Agent 本次不可用" in note


def test_fork_path_runs_critic(tmp_path: Path, monkeypatch):
    from quantbench.agent.coordinator import Coordinator
    from quantbench.artifact.store import ArtifactStore

    _patch_fetch(tmp_path, monkeypatch, _sample_ohlcv())
    monkeypatch.setattr("quantbench.api.run_reader.RUNS_DIR", tmp_path / "runs")
    parent_code = "def compute(df):\n    return df['close'].pct_change(10).fillna(0.0)\n"
    store = ArtifactStore(tmp_path / "runs")
    coordinator = Coordinator(
        run_store=store,
        llm=FakeLLMClient(_script(parent_code)),
        critic_llm=JsonCriticLLM(
            {
                "verdict": "PROMISING",
                "agrees_with_deterministic_verdict": True,
                "critique": "parent ok",
                "narrative_consistency_issues": [],
                "recommended_next_steps": [],
            }
        ),
    )
    parent = coordinator.run("先跑父实验")

    fork_code = "def compute(df):\n    return df['close'].pct_change(5).fillna(0.0)\n"
    fork_critic = JsonCriticLLM(
        {
            "verdict": "PROMISING",
            "agrees_with_deterministic_verdict": True,
            "critique": "fork ok",
            "narrative_consistency_issues": [],
            "recommended_next_steps": [],
        }
    )
    forked = Coordinator(
        run_store=store,
        llm=FakeLLMClient([("tools", [("run_signal_backtest", {"code": fork_code, "cost_bps": 5})]), ("text", "fork done")]),
        critic_llm=fork_critic,
    ).run_fork(parent.run_id, "缩短窗口")

    critic = json.loads((forked.run_dir / "critic_report.json").read_text(encoding="utf-8"))
    assert critic["status"] == "ok"
    assert critic["critique"] == "fork ok"


def test_critic_report_markdown_distinguishes_unknown_from_disagree():
    from quantbench.review.critic import CriticReport

    unknown = CriticReport(
        status="ok",
        verdict="PROMISING",
        agrees_with_deterministic_verdict=None,
        critique="no explicit agreement signal",
        narrative_consistency_issues=[],
        recommended_next_steps=[],
    )
    disagree = CriticReport(
        status="ok",
        verdict="WEAK",
        agrees_with_deterministic_verdict=False,
        critique="explicitly disagrees",
        narrative_consistency_issues=[],
        recommended_next_steps=[],
    )
    # None must render distinctly from False - "unknown" is not "disagree".
    assert "未知" in unknown.to_markdown()
    assert "否" in disagree.to_markdown()
    assert "未知" not in disagree.to_markdown()
