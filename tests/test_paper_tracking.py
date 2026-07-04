import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml


def _write_run(runs_dir: Path, run_id: str, *, sharpe: float = 1.2, verdict: str = "STRONG"):
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True)
    manifest = {
        "run_id": run_id,
        "user_request": "momentum factor",
        "created_at": "2026-07-01T00:00:00+00:00",
        "summary": "done",
        "metrics": {"sharpe": sharpe},
        "review": {"verdict": verdict, "verdict_reason": "reason", "findings": []},
        "warnings": [],
    }
    config = {"hypothesis": "momentum factor", "data_path": "/tmp/does-not-matter.parquet", "universe": None}
    (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "review_report.json").write_text(json.dumps(manifest["review"]), encoding="utf-8")
    (run_dir / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    (run_dir / "signal.py").write_text(
        "def compute(df):\n    return df['close'].pct_change(20).fillna(0)\n", encoding="utf-8"
    )
    return run_dir


@pytest.fixture
def patched_runs(tmp_path, monkeypatch):
    runs_dir = tmp_path / "runs"
    monkeypatch.setattr("quantbench.api.run_reader.RUNS_DIR", runs_dir)
    return runs_dir


def _returns_series(dates: list[str], values: list[float]) -> pd.Series:
    return pd.Series(values, index=pd.to_datetime(dates, utc=True))


def test_record_daily_paper_tracking_accrues_new_days_only(patched_runs, tmp_path, monkeypatch):
    from quantbench.factors import paper_tracking as pt
    from quantbench.factors.entry import build_entry_from_run
    from quantbench.factors.store import FactorStore

    _write_run(patched_runs, "run_strong", sharpe=1.0)
    store = FactorStore(tmp_path / "factors")
    entry = build_entry_from_run("run_strong", "strong_momentum")
    store.save_factor(entry)
    tracking_store = pt.PaperTrackingStore(tmp_path / "factors")

    call_count = {"n": 0}

    def fake_refresh_and_backtest(run_id, conn, refresh_start):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _returns_series(["2026-07-02", "2026-07-03"], [0.01, 0.01])
        # A later check (after a multi-day gap) sees a longer history in one call -
        # no separate "catch up missed days" logic should be needed.
        return _returns_series(
            ["2026-07-02", "2026-07-03", "2026-07-04", "2026-07-05"], [0.01, 0.01, 0.01, 0.01]
        )

    monkeypatch.setattr(pt, "refresh_and_backtest", fake_refresh_and_backtest)

    first = pt.record_daily_paper_tracking(entry, store=store, tracking_store=tracking_store, conn=None)
    assert first["days_tracked"] == 2

    second = pt.record_daily_paper_tracking(entry, store=store, tracking_store=tracking_store, conn=None)
    # Only the 2 genuinely new days should be appended, not all 4 again.
    assert second["days_tracked"] == 4

    history = tracking_store.read("strong_momentum")
    assert len(history.daily_returns) == 4
    assert len(history.decay_checks) == 2


def test_record_daily_paper_tracking_no_new_data_is_a_noop(patched_runs, tmp_path, monkeypatch):
    from quantbench.factors import paper_tracking as pt
    from quantbench.factors.entry import build_entry_from_run
    from quantbench.factors.store import FactorStore

    _write_run(patched_runs, "run_strong", sharpe=1.0)
    store = FactorStore(tmp_path / "factors")
    entry = build_entry_from_run("run_strong", "strong_momentum")
    store.save_factor(entry)
    tracking_store = pt.PaperTrackingStore(tmp_path / "factors")

    monkeypatch.setattr(pt, "refresh_and_backtest", lambda run_id, conn, refresh_start: pd.Series(dtype="float64"))

    result = pt.record_daily_paper_tracking(entry, store=store, tracking_store=tracking_store, conn=None)
    assert result["status"] == "no_new_data"
    assert tracking_store.read("strong_momentum") is None


def test_record_daily_paper_tracking_alert_transitions_to_decayed(patched_runs, tmp_path, monkeypatch):
    from quantbench.factors import paper_tracking as pt
    from quantbench.factors.entry import build_entry_from_run
    from quantbench.factors.store import FactorStore

    _write_run(patched_runs, "run_strong", sharpe=2.0)
    store = FactorStore(tmp_path / "factors")
    entry = build_entry_from_run("run_strong", "strong_momentum")
    store.save_factor(entry)
    tracking_store = pt.PaperTrackingStore(tmp_path / "factors")

    # Negative-drift daily returns give a strongly negative recent Sharpe against
    # an original Sharpe of 2.0 - guaranteed to land in STATUS_ALERT.
    dates = pd.date_range("2026-07-02", periods=10, freq="1D").strftime("%Y-%m-%d").tolist()
    values = list(np.random.default_rng(1).normal(-0.01, 0.001, 10))
    monkeypatch.setattr(
        pt, "refresh_and_backtest", lambda run_id, conn, refresh_start: _returns_series(dates, values)
    )

    result = pt.record_daily_paper_tracking(entry, store=store, tracking_store=tracking_store, conn=None)

    assert result["status"] == "alert"
    assert result["lifecycle_state"] == "decayed"
    assert store.load_factor("strong_momentum").lifecycle_state == "decayed"


def test_record_daily_paper_tracking_does_not_promote_before_thresholds(patched_runs, tmp_path, monkeypatch):
    from quantbench.factors import paper_tracking as pt
    from quantbench.factors.entry import build_entry_from_run
    from quantbench.factors.store import FactorStore

    _write_run(patched_runs, "run_strong", sharpe=0.5)
    store = FactorStore(tmp_path / "factors")
    entry = build_entry_from_run("run_strong", "strong_momentum")
    store.save_factor(entry)
    tracking_store = pt.PaperTrackingStore(tmp_path / "factors")

    # Only 5 clean days recorded - short of PAPER_TRACKING_PROMOTION_MIN_DAYS (20).
    # A small amount of noise around a positive mean avoids the zero-std
    # degenerate case a perfectly constant return series would hit.
    dates = pd.date_range("2026-07-02", periods=5, freq="1D").strftime("%Y-%m-%d").tolist()
    values = list(np.random.default_rng(42).normal(0.002, 0.0002, 5))
    monkeypatch.setattr(
        pt, "refresh_and_backtest", lambda run_id, conn, refresh_start: _returns_series(dates, values)
    )

    result = pt.record_daily_paper_tracking(entry, store=store, tracking_store=tracking_store, conn=None)

    assert result["status"] == "ok"
    assert result["lifecycle_state"] == "paper_tracking"
    assert store.load_factor("strong_momentum").lifecycle_state == "paper_tracking"


def test_run_paper_tracking_pass_only_processes_paper_tracking_and_live_candidate(
    patched_runs, tmp_path, monkeypatch
):
    from quantbench.factors import paper_tracking as pt
    from quantbench.factors.entry import build_entry_from_run
    from quantbench.factors.store import FactorStore

    _write_run(patched_runs, "run_strong", sharpe=1.0, verdict="STRONG")
    _write_run(patched_runs, "run_weak", sharpe=0.5, verdict="WEAK")
    store = FactorStore(tmp_path / "factors")
    store.save_factor(build_entry_from_run("run_strong", "strong_momentum"))  # -> paper_tracking
    store.save_factor(build_entry_from_run("run_weak", "weak_momentum"))  # -> research, should be skipped

    monkeypatch.setattr(
        pt, "refresh_and_backtest", lambda run_id, conn, refresh_start: _returns_series(["2026-07-02"], [0.001])
    )

    results = pt.run_paper_tracking_pass(conn=None, store=store)

    assert [item["name"] for item in results] == ["strong_momentum"]
