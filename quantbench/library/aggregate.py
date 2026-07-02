from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean
from typing import Any

from quantbench.api import run_reader
from quantbench.library.index import ExperimentIndex


def summarize(index: ExperimentIndex | None = None, by: tuple[str, ...] = ("factor_family", "asset_class")) -> list[dict[str, Any]]:
    index = index or ExperimentIndex.build()
    groups: dict[tuple[Any, ...], list] = defaultdict(list)
    for record in index.records:
        groups[tuple(getattr(record, field) for field in by)].append(record)

    rows = []
    for key, records in sorted(groups.items(), key=lambda item: item[0]):
        row = {field: value for field, value in zip(by, key)}
        sharpes = [record.sharpe for record in records if record.sharpe is not None]
        oos_pairs = [(record.sharpe, record.oos_sharpe) for record in records if record.sharpe and record.oos_sharpe is not None]
        verdict_counts = Counter(record.verdict for record in records if record.verdict)
        row.update(
            {
                "count": len(records),
                "verdict_counts": dict(sorted(verdict_counts.items())),
                "sharpe_mean": mean(sharpes) if sharpes else None,
                "sharpe_min": min(sharpes) if sharpes else None,
                "sharpe_max": max(sharpes) if sharpes else None,
                "oos_decay_count": sum(1 for sharpe, oos in oos_pairs if oos < sharpe),
                "cost_sensitive_count": sum(1 for record in records if _has_cost_warning(record.run_id)),
                "sample_warning": len(records) < 2,
            }
        )
        rows.append(row)
    return rows


def _has_cost_warning(run_id: str) -> bool:
    manifest = run_reader.read_manifest(run_id) or {}
    review = manifest.get("review") or {}
    for finding in review.get("findings") or []:
        if finding.get("check") == "cost_sensitivity" and finding.get("severity") in {"warning", "critical"}:
            return True
    return False
