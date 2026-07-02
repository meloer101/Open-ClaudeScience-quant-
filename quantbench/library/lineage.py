from __future__ import annotations

import difflib
from typing import Any

from quantbench.api import run_reader
from quantbench.library.index import ExperimentIndex
from quantbench.library.record import ExperimentRecord, signal_path


METRIC_DELTA_FIELDS = ("sharpe", "annual_return", "max_drawdown", "turnover_annual", "ic_mean", "oos_sharpe")


def lineage(run_id: str, index: ExperimentIndex | None = None) -> dict[str, Any]:
    index = index or ExperimentIndex.build()
    records_by_id = {record.run_id: record for record in index.records}
    if run_id not in records_by_id:
        raise KeyError(run_id)

    chain, missing_parent = _chain_to_root(records_by_id[run_id], records_by_id)
    edges = []
    for parent, child in zip(chain, chain[1:]):
        edges.append(
            {
                "parent_run_id": parent.run_id,
                "child_run_id": child.run_id,
                "signal_diff": diff_signals(parent.run_id, child.run_id),
                "metric_delta": diff_metrics(parent, child),
                "verdict_delta": {"from": parent.verdict, "to": child.verdict},
            }
        )

    descendants = _descendants(run_id, records_by_id)
    return {
        "run_id": run_id,
        "chain": [record.to_dict() for record in chain],
        "edges": edges,
        "descendants": [record.to_dict() for record in descendants],
        # run_id of a parent pointer that could not be resolved (parent run
        # deleted), or None when the chain reaches a genuine root.
        "parent_missing": missing_parent,
    }


def diff_signals(parent_run_id: str, child_run_id: str) -> str:
    parent_lines = _read_signal_lines(parent_run_id)
    child_lines = _read_signal_lines(child_run_id)
    # Input lines already carry trailing "\n", so leave lineterm at its default
    # ("\n") - passing lineterm="" here would glue the "@@" hunk header onto the
    # first content line and produce a malformed diff.
    return "".join(
        difflib.unified_diff(
            parent_lines,
            child_lines,
            fromfile=f"{parent_run_id}/signal.py",
            tofile=f"{child_run_id}/signal.py",
        )
    )


def diff_metrics(parent: ExperimentRecord, child: ExperimentRecord) -> dict[str, float | None]:
    deltas: dict[str, float | None] = {}
    for field in METRIC_DELTA_FIELDS:
        before = getattr(parent, field)
        after = getattr(child, field)
        deltas[field] = None if before is None or after is None else after - before
    return deltas


def _chain_to_root(
    record: ExperimentRecord, records_by_id: dict[str, ExperimentRecord]
) -> tuple[list[ExperimentRecord], str | None]:
    """Walk parent pointers to the root. Returns the ordered chain plus the
    run_id of a dangling parent pointer (parent run deleted), or None if the
    chain reaches a genuine root or is truncated by a cycle."""
    chain = [record]
    seen = {record.run_id}
    current = record
    missing_parent: str | None = None
    while current.parent_run_id:
        parent = records_by_id.get(current.parent_run_id)
        if parent is None:
            missing_parent = current.parent_run_id
            break
        if parent.run_id in seen:
            break
        chain.append(parent)
        seen.add(parent.run_id)
        current = parent
    return list(reversed(chain)), missing_parent


def _descendants(run_id: str, records_by_id: dict[str, ExperimentRecord]) -> list[ExperimentRecord]:
    children_by_parent: dict[str, list[ExperimentRecord]] = {}
    for record in records_by_id.values():
        if record.parent_run_id:
            children_by_parent.setdefault(record.parent_run_id, []).append(record)
    ordered: list[ExperimentRecord] = []
    stack = sorted(children_by_parent.get(run_id, []), key=lambda item: item.created_at)
    while stack:
        child = stack.pop(0)
        ordered.append(child)
        stack[0:0] = sorted(children_by_parent.get(child.run_id, []), key=lambda item: item.created_at)
    return ordered


def _read_signal_lines(run_id: str) -> list[str]:
    path = signal_path(run_id)
    if not path.exists():
        return []
    return [line + "\n" for line in path.read_text(encoding="utf-8").splitlines()]
