import json
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner


def _write_run(
    runs_dir: Path,
    run_id: str,
    *,
    verdict: str = "PROMISING",
    hypothesis: str = "momentum factor on AAPL",
    signal_code: str = "def compute(df):\n    lookback = 20\n    return df['close'].pct_change(lookback).fillna(0)\n",
):
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    findings = [
        {
            "check": "parameter_stability",
            "severity": "warning",
            "message": "sensitive to lookback",
            "detail": {"sharpe_spread": 0.8},
        }
    ]
    manifest = {
        "run_id": run_id,
        "user_request": hypothesis,
        "created_at": "2026-07-01T00:00:00+00:00",
        "summary": "done",
        "metrics": {"sharpe": 1.25, "annual_return": 0.2, "max_drawdown": -0.1},
        "review": {"verdict": verdict, "verdict_reason": "reason", "findings": findings},
        "warnings": ["review warning"],
    }
    config = {
        "hypothesis": hypothesis,
        "data_path": "/tmp/data_cache/yfinance_equity_AAPL_1d.parquet",
        "universe": None,
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "review_report.json").write_text(json.dumps(manifest["review"]), encoding="utf-8")
    (run_dir / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    (run_dir / "signal.py").write_text(signal_code, encoding="utf-8")
    return run_dir


@pytest.fixture
def patched_runs(tmp_path, monkeypatch):
    runs_dir = tmp_path / "runs"
    monkeypatch.setattr("quantbench.api.run_reader.RUNS_DIR", runs_dir)
    return runs_dir


def test_build_factor_entry_rejects_rejected_runs_unless_forced(patched_runs):
    from quantbench.factors.entry import RejectedFactorError, build_entry_from_run

    _write_run(patched_runs, "run_rejected", verdict="REJECTED")

    with pytest.raises(RejectedFactorError):
        build_entry_from_run("run_rejected", "bad_momentum")

    forced = build_entry_from_run("run_rejected", "bad_momentum", force=True)

    assert forced.saved_from_rejected is True
    assert forced.source_verdict == "REJECTED"
    assert forced.source_findings[0]["check"] == "parameter_stability"


def test_factor_save_load_list_and_rebuild_index(patched_runs, tmp_path):
    from quantbench.factors.entry import build_entry_from_run
    from quantbench.factors.store import FactorStore

    _write_run(patched_runs, "run_promising")
    store = FactorStore(tmp_path / "factors")
    entry = build_entry_from_run("run_promising", "momentum_20d")

    store.save_factor(entry)
    loaded = store.load_factor("momentum_20d")
    rows = store.list_factors(family="momentum", min_verdict="WEAK")

    assert loaded.code.startswith("def compute")
    assert loaded.source_metrics["sharpe"] == 1.25
    assert rows[0].name == "momentum_20d"
    assert (tmp_path / "factors" / "INDEX.json").exists()

    (tmp_path / "factors" / "INDEX.json").unlink()
    rebuilt = store.list_factors()
    assert [row.name for row in rebuilt] == ["momentum_20d"]


def test_factor_parameters_can_be_extracted_and_overridden():
    from quantbench.factors.parametrize import apply_overrides, extract_parameters

    code = "def compute(df):\n    lookback = 20\n    return df['close'].pct_change(lookback).fillna(0)\n"

    params = extract_parameters(code)
    updated = apply_overrides(code, {"lookback": "60"})

    assert params[0]["name"] == "lookback"
    assert params[0]["value"] == 20.0
    assert "lookback = 60" in updated
    assert "pct_change(lookback)" in updated


def test_apply_overrides_edits_the_correct_literal_when_code_has_two_of_them():
    """Regression: extract_parameters used to enumerate literals with
    ast.walk() (breadth-first) while apply_overrides replaced them via
    ast.NodeTransformer (depth-first). Those orders disagree once a factor
    has more than one perturbable literal at different tree depths, so
    overriding the parameter the caller named (as reported by extract/show)
    would silently edit a *different* literal instead. Must stay in
    left-to-right source order on both sides."""
    from quantbench.factors.parametrize import apply_overrides, extract_parameters

    code = "def compute(df):\n    return df['close'].rolling(20).mean() - df['close'].shift(5)\n"

    params = extract_parameters(code)
    assert [p["value"] for p in params] == [20.0, 5.0]

    updated_p2 = apply_overrides(code, {"p2": 99})
    assert "shift(99)" in updated_p2
    assert "rolling(20)" in updated_p2

    updated_p1 = apply_overrides(code, {"p1": 42})
    assert "rolling(42)" in updated_p1
    assert "shift(5)" in updated_p1


def test_factor_cli_save_list_show_uses_factor_store(patched_runs, tmp_path, monkeypatch):
    from quantbench.cli import main

    _write_run(patched_runs, "run_promising")
    monkeypatch.setattr("quantbench.cli.DEFAULT_FACTORS_DIR", tmp_path / "factors")

    runner = CliRunner()
    saved = runner.invoke(main, ["factor", "save", "run_promising", "--name", "momentum_20d"])
    listed = runner.invoke(main, ["factor", "list", "--family", "momentum"])
    shown = runner.invoke(main, ["factor", "show", "momentum_20d"])

    assert saved.exit_code == 0, saved.output
    assert "Saved factor momentum_20d" in saved.output
    assert "momentum_20d" in listed.output
    assert "source_verdict: PROMISING" in shown.output
    assert "sensitive to lookback" in shown.output


def test_run_from_factor_applies_param_override_and_records_lineage(patched_runs, tmp_path):
    from _fakes import FakeLLMClient

    from quantbench.agent.coordinator import Coordinator
    from quantbench.artifact.store import ArtifactStore
    from quantbench.factors.entry import build_entry_from_run
    from quantbench.factors.store import FactorStore

    _write_run(patched_runs, "run_promising")
    store = FactorStore(tmp_path / "factors")
    store.save_factor(build_entry_from_run("run_promising", "momentum_20d"))
    llm = FakeLLMClient([("text", "started from factor")])
    coordinator = Coordinator(run_store=ArtifactStore(tmp_path / "runs_out"), llm=llm)

    result = coordinator.run_from_factor("momentum_20d", {"lookback": "60"}, "test on AAPL", factor_store=store)

    config = yaml.safe_load((result.run_dir / "config.yaml").read_text(encoding="utf-8"))
    user_prompt = llm.calls[0][0][1]["content"]
    assert config["derived_from_factor"] == "momentum_20d"
    assert "lookback = 60" in user_prompt
    # config.hypothesis / the experiment library's factor_family classifier /
    # Skill matching must all see the clean request text, not the seed prompt
    # (which embeds reference code and reviewer-finding text that could
    # produce misleading classifications or spurious Skill matches).
    assert config["hypothesis"] == "test on AAPL"
