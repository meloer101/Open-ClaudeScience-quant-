"""Paper tracking (GAP 5.2): daily accrual of a factor's hypothetical
"if traded on this signal" return, driving the lifecycle state machine's
paper_tracking -> live_candidate / decayed transitions.

Deliberately thin: the actual "refresh data, recompute compute(), rerun the
backtest" work is quantbench.monitor.pipeline.refresh_and_backtest, already
built and tested for decay monitoring. This module only adds the part that
didn't exist - persisting a growing daily-return history instead of only
looking at a single point-in-time ratio, and turning the existing decay
status into a lifecycle transition.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from quantbench.config import (
    FACTORS_DIR,
    PAPER_TRACKING_PROMOTION_MIN_CONSECUTIVE_OK,
    PAPER_TRACKING_PROMOTION_MIN_DAYS,
)
from quantbench.factors.entry import FactorEntry
from quantbench.factors.lifecycle import LIVE_CANDIDATE, PAPER_TRACKING, next_state_from_decay
from quantbench.factors.store import FactorStore
from quantbench.monitor.decay import compute_decay_report
from quantbench.monitor.pipeline import refresh_and_backtest


@dataclass
class PaperTrackingHistory:
    factor_name: str
    source_run_id: str
    daily_returns: list[dict[str, Any]] = field(default_factory=list)
    decay_checks: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PaperTrackingHistory":
        return cls(
            factor_name=str(payload["factor_name"]),
            source_run_id=str(payload["source_run_id"]),
            daily_returns=list(payload.get("daily_returns") or []),
            decay_checks=list(payload.get("decay_checks") or []),
        )


class PaperTrackingStore:
    def __init__(self, factors_dir: Path = FACTORS_DIR) -> None:
        self.dir = Path(factors_dir) / "paper_tracking"

    def read(self, factor_name: str) -> PaperTrackingHistory | None:
        path = self._path(factor_name)
        if not path.exists():
            return None
        return PaperTrackingHistory.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def write(self, history: PaperTrackingHistory) -> Path:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self._path(history.factor_name)
        path.write_text(json.dumps(history.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def _path(self, factor_name: str) -> Path:
        return self.dir / f"{factor_name}.json"


def record_daily_paper_tracking(
    entry: FactorEntry,
    *,
    store: FactorStore | None = None,
    tracking_store: PaperTrackingStore | None = None,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> dict[str, Any]:
    """Refreshes and recomputes entry's source run since the last recorded
    day (or since entry.saved_at if this is the first check), appends any new
    daily returns, evaluates decay against the run's original Sharpe, and
    applies a lifecycle transition if warranted. Safe to call after a gap of
    several days - refresh_and_backtest recomputes the whole recomputed
    series from refresh_start, so missed days are caught up in one call
    rather than needing separate backfill logic."""
    store = store or FactorStore()
    # See run_paper_tracking_pass's comment: derive from store's directory so
    # a custom FactorStore location can't silently split from its own
    # paper-tracking history.
    tracking_store = tracking_store or PaperTrackingStore(store.factors_dir)

    history = tracking_store.read(entry.name)
    if history is None:
        history = PaperTrackingHistory(factor_name=entry.name, source_run_id=entry.source_run_id)
        refresh_start = entry.saved_at
    else:
        last_date = history.daily_returns[-1]["date"] if history.daily_returns else entry.saved_at
        refresh_start = str(pd.Timestamp(last_date))

    full_returns = refresh_and_backtest(entry.source_run_id, conn, refresh_start)
    known_dates = {row["date"] for row in history.daily_returns}
    new_returns = full_returns[~full_returns.index.map(lambda ts: str(ts)).isin(known_dates)]

    if new_returns.empty:
        return {
            "name": entry.name,
            "lifecycle_state": entry.lifecycle_state,
            "status": "no_new_data",
            "days_tracked": len(history.daily_returns),
        }

    for timestamp, value in new_returns.items():
        history.daily_returns.append({"date": str(timestamp), "return": round(float(value), 8)})

    original_sharpe = float(entry.source_metrics.get("sharpe") or 0.0)
    recent = pd.Series(
        [row["return"] for row in history.daily_returns],
        index=pd.to_datetime([row["date"] for row in history.daily_returns], utc=True),
    )
    decay_report = compute_decay_report(original_sharpe, recent, recent.index[0])
    history.decay_checks.append({"checked_at": decay_report.checked_at, "status": decay_report.status})
    tracking_store.write(history)

    days_tracked = len(history.daily_returns)
    consecutive_ok = _trailing_consecutive_ok(history.decay_checks)
    new_state = next_state_from_decay(
        entry.lifecycle_state,
        decay_report.status,
        days_tracked=days_tracked,
        consecutive_ok=consecutive_ok,
        promotion_min_days=PAPER_TRACKING_PROMOTION_MIN_DAYS,
        promotion_min_consecutive_ok=PAPER_TRACKING_PROMOTION_MIN_CONSECUTIVE_OK,
    )
    lifecycle_state = entry.lifecycle_state
    if new_state is not None:
        updated = store.transition_lifecycle(entry.name, new_state, reason=decay_report.detail)
        lifecycle_state = updated.lifecycle_state

    return {
        "name": entry.name,
        "lifecycle_state": lifecycle_state,
        "status": decay_report.status,
        "days_tracked": days_tracked,
        "recent_sharpe": decay_report.recent_sharpe,
    }


def run_paper_tracking_pass(
    conn: duckdb.DuckDBPyConnection | None = None,
    *,
    store: FactorStore | None = None,
    tracking_store: PaperTrackingStore | None = None,
) -> list[dict[str, Any]]:
    store = store or FactorStore()
    # Derived from store's own directory rather than defaulted independently -
    # a custom FactorStore location must keep its paper-tracking history
    # alongside it, not split across store's directory and a separately
    # defaulted PaperTrackingStore() pointing elsewhere.
    tracking_store = tracking_store or PaperTrackingStore(store.factors_dir)
    candidates = store.list_factors(lifecycle_state=[PAPER_TRACKING, LIVE_CANDIDATE])
    results = []
    for entry in candidates:
        try:
            results.append(record_daily_paper_tracking(entry, store=store, tracking_store=tracking_store, conn=conn))
        except Exception as exc:  # noqa: BLE001 - one factor's data issue shouldn't block the whole pass
            results.append({"name": entry.name, "lifecycle_state": entry.lifecycle_state, "error": str(exc)})
    return results


def _trailing_consecutive_ok(decay_checks: list[dict[str, Any]]) -> int:
    count = 0
    for check in reversed(decay_checks):
        if check.get("status") != "ok":
            break
        count += 1
    return count
