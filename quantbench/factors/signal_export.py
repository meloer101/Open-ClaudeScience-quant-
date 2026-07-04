"""Signal export (GAP 5.3): the research-to-production handoff surface. Given
a saved cross-sectional FactorEntry, produce the current period's target
weights plus enough provenance (factor version hash, source run/verdict,
lifecycle state, known limitations) for a downstream system to decide whether
to trust and consume it.

Deliberately thin: reuses monitor.pipeline.refresh_and_recompute_weights for
"refresh data, recompute compute(), get the latest weight vector" rather than
building a second refresh pipeline - see that function's docstring for why
the cross-sectional engine result already has this available.

v1 is cross-sectional factors only - GAP's "a factor + a universe" framing
doesn't naturally extend to a single-symbol factor (no "universe" concept),
so single-asset export is left for a future increment rather than forced in
here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import duckdb

from quantbench.artifact.store import text_sha256
from quantbench.factors.entry import FactorEntry
from quantbench.monitor.pipeline import refresh_and_recompute_weights


def build_signal_export(entry: FactorEntry, *, conn: duckdb.DuckDBPyConnection | None = None) -> dict[str, Any]:
    weights = refresh_and_recompute_weights(entry.source_run_id, conn)
    if weights is None:
        return {
            "status": "unsupported",
            "reason": "single_asset_export_not_supported",
            "factor_name": entry.name,
            "source_run_id": entry.source_run_id,
            "error": (
                f"signal export is not supported for factor {entry.name!r}: its source run "
                f"{entry.source_run_id!r} is not a cross-sectional run (no universe of target "
                "weights to export). Single-asset signal export is not implemented yet."
            ),
            "message": (
                f"signal export is not supported for factor {entry.name!r}: its source run "
                f"{entry.source_run_id!r} is not a cross-sectional run."
            ),
            "next_step": "Use a cross-sectional factor with a saved universe, or keep this as a research-only artifact.",
        }

    return {
        "factor_name": entry.name,
        "factor_version_hash": f"sha256:{text_sha256(entry.code)}",
        "as_of": str(weights.name),
        "target_weights": {str(symbol): round(float(value), 8) for symbol, value in weights.items()},
        "source_run_id": entry.source_run_id,
        "source_verdict": entry.source_verdict,
        "lifecycle_state": entry.lifecycle_state,
        "known_limitations": entry.source_findings,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "data_as_of_note": (
            "target_weights are computed from data refreshed at export time, not the original "
            "backtest-period data - this is a live, current-period signal, not a historical replay."
        ),
        "risk_disclaimer": (
            "Research export only. These target weights are not investment advice and are not an "
            "automated trading instruction."
        ),
    }
