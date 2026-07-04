import json
from pathlib import Path

import pytest
import yaml


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
    manifest = {
        "run_id": run_id,
        "user_request": hypothesis,
        "created_at": "2026-07-01T00:00:00+00:00",
        "summary": "done",
        "metrics": {"sharpe": 1.25, "annual_return": 0.2, "max_drawdown": -0.1},
        "review": {"verdict": verdict, "verdict_reason": "reason", "findings": []},
        "warnings": [],
    }
    config = {"hypothesis": hypothesis, "data_path": "/tmp/does-not-matter.parquet", "universe": None}
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


def test_initial_state_for_verdict_matches_alive_verdicts():
    from quantbench.factors.lifecycle import PAPER_TRACKING, RESEARCH, initial_state_for_verdict

    assert initial_state_for_verdict("STRONG") == PAPER_TRACKING
    assert initial_state_for_verdict("PROMISING") == PAPER_TRACKING
    assert initial_state_for_verdict("WEAK") == RESEARCH
    assert initial_state_for_verdict("REJECTED") == RESEARCH
    assert initial_state_for_verdict(None) == RESEARCH


def test_next_state_from_decay_transitions():
    from quantbench.factors.lifecycle import DECAYED, LIVE_CANDIDATE, PAPER_TRACKING, next_state_from_decay

    # A single alert always transitions to decayed.
    assert (
        next_state_from_decay(
            PAPER_TRACKING, "alert", days_tracked=5, consecutive_ok=0, promotion_min_days=20, promotion_min_consecutive_ok=3
        )
        == DECAYED
    )

    # Promotion requires both enough elapsed days AND enough consecutive ok checks.
    assert (
        next_state_from_decay(
            PAPER_TRACKING, "ok", days_tracked=25, consecutive_ok=4, promotion_min_days=20, promotion_min_consecutive_ok=3
        )
        == LIVE_CANDIDATE
    )

    # A single lucky ok day does not promote - neither threshold met yet.
    assert (
        next_state_from_decay(
            PAPER_TRACKING, "ok", days_tracked=1, consecutive_ok=1, promotion_min_days=20, promotion_min_consecutive_ok=3
        )
        is None
    )

    # research/decayed/retired are not eligible for automated transitions at all.
    assert (
        next_state_from_decay(
            "research", "alert", days_tracked=99, consecutive_ok=0, promotion_min_days=20, promotion_min_consecutive_ok=3
        )
        is None
    )


def test_next_state_from_decay_never_returns_retired():
    from quantbench.factors.lifecycle import RETIRED, next_state_from_decay

    for status in ("ok", "watch", "alert", "insufficient_data"):
        for current in ("paper_tracking", "live_candidate"):
            assert (
                next_state_from_decay(
                    current,
                    status,
                    days_tracked=1000,
                    consecutive_ok=1000,
                    promotion_min_days=1,
                    promotion_min_consecutive_ok=1,
                )
                != RETIRED
            )


def test_validate_transition_rejects_illegal_moves():
    from quantbench.factors.lifecycle import validate_transition

    validate_transition("paper_tracking", "live_candidate")  # legal, no raise
    with pytest.raises(ValueError, match="illegal lifecycle transition"):
        validate_transition("retired", "paper_tracking")
    with pytest.raises(ValueError, match="illegal lifecycle transition"):
        validate_transition("research", "live_candidate")
    with pytest.raises(ValueError, match="unknown lifecycle state"):
        validate_transition("research", "bogus_state")


def test_build_entry_from_run_sets_initial_lifecycle_state_and_history(patched_runs):
    from quantbench.factors.entry import build_entry_from_run

    _write_run(patched_runs, "run_strong", verdict="STRONG")
    entry = build_entry_from_run("run_strong", "strong_momentum")

    assert entry.lifecycle_state == "paper_tracking"
    assert len(entry.lifecycle_history) == 1
    assert entry.lifecycle_history[0]["from_state"] is None
    assert entry.lifecycle_history[0]["to_state"] == "paper_tracking"

    _write_run(patched_runs, "run_weak", verdict="WEAK")
    weak_entry = build_entry_from_run("run_weak", "weak_momentum")
    assert weak_entry.lifecycle_state == "research"


def test_factor_entry_from_dict_defaults_lifecycle_fields_for_old_files():
    from quantbench.factors.entry import FactorEntry

    old_payload = {
        "name": "legacy_factor",
        "code": "def compute(df):\n    return df['close']\n",
        "source_run_id": "run_old",
    }
    entry = FactorEntry.from_dict(old_payload)

    assert entry.lifecycle_state == "research"
    assert entry.lifecycle_history == []


def test_transition_lifecycle_persists_and_appends_audit_history(patched_runs, tmp_path):
    from quantbench.factors.entry import build_entry_from_run
    from quantbench.factors.store import FactorStore

    _write_run(patched_runs, "run_strong", verdict="STRONG")
    store = FactorStore(tmp_path / "factors")
    store.save_factor(build_entry_from_run("run_strong", "strong_momentum"))

    updated = store.transition_lifecycle("strong_momentum", "live_candidate", reason="20 clean days")
    assert updated.lifecycle_state == "live_candidate"
    assert len(updated.lifecycle_history) == 2
    assert updated.lifecycle_history[-1]["reason"] == "20 clean days"

    reloaded = store.load_factor("strong_momentum")
    assert reloaded.lifecycle_state == "live_candidate"
    assert len(reloaded.lifecycle_history) == 2


def test_transition_lifecycle_rejects_illegal_transition(patched_runs, tmp_path):
    from quantbench.factors.entry import build_entry_from_run
    from quantbench.factors.store import FactorStore

    _write_run(patched_runs, "run_weak", verdict="WEAK")
    store = FactorStore(tmp_path / "factors")
    store.save_factor(build_entry_from_run("run_weak", "weak_momentum"))

    with pytest.raises(ValueError, match="illegal lifecycle transition"):
        store.transition_lifecycle("weak_momentum", "live_candidate", reason="skip paper_tracking")


def test_list_factors_filters_by_lifecycle_state(patched_runs, tmp_path):
    from quantbench.factors.entry import build_entry_from_run
    from quantbench.factors.store import FactorStore

    _write_run(patched_runs, "run_strong", verdict="STRONG")
    _write_run(patched_runs, "run_weak", verdict="WEAK")
    store = FactorStore(tmp_path / "factors")
    store.save_factor(build_entry_from_run("run_strong", "strong_momentum"))
    store.save_factor(build_entry_from_run("run_weak", "weak_momentum"))

    tracked = store.list_factors(lifecycle_state="paper_tracking")
    assert [entry.name for entry in tracked] == ["strong_momentum"]

    both = store.list_factors(lifecycle_state=["paper_tracking", "research"])
    assert {entry.name for entry in both} == {"strong_momentum", "weak_momentum"}
