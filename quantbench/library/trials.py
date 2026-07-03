from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

@dataclass(frozen=True)
class TrialCount:
    prior_trials: int
    matched_run_ids: list[str]


def universe_signature(universe: dict[str, Any] | None) -> str:
    universe = universe or {}
    symbols = sorted(str(symbol) for symbol in universe.get("symbols") or [])
    payload = {
        "asset_class": universe.get("asset_class"),
        "provider": universe.get("provider") or universe.get("source"),
        "symbols": symbols,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def count_trials(universe_signature: str, start: str, end: str) -> TrialCount:
    from quantbench.library.index import ExperimentIndex

    if not universe_signature:
        return TrialCount(0, [])
    query_start = _date_key(start)
    query_end = _date_key(end)
    matched: list[str] = []
    for record in ExperimentIndex.build().records:
        if record.universe_signature != universe_signature:
            continue
        if not _windows_overlap(query_start, query_end, _date_key(record.window_start), _date_key(record.window_end)):
            continue
        matched.append(record.run_id)
    return TrialCount(prior_trials=len(matched), matched_run_ids=matched)


def _date_key(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _windows_overlap(
    left_start: datetime | None,
    left_end: datetime | None,
    right_start: datetime | None,
    right_end: datetime | None,
) -> bool:
    if None in {left_start, left_end, right_start, right_end}:
        return False
    return left_start <= right_end and right_start <= left_end
