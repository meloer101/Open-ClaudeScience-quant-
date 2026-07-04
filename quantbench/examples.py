from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from quantbench.config import RUNS_DIR


EXAMPLE_RUN_ID = "run_20260704_000000_example"


def seed_example_runs(runs_dir: Path = RUNS_DIR) -> dict[str, int | list[str]]:
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_dir = runs_dir / EXAMPLE_RUN_ID
    created = 0
    if not run_dir.exists():
        run_dir.mkdir()
        created = 1
    manifest = {
        "run_id": EXAMPLE_RUN_ID,
        "user_request": "Example: crypto cross-sectional momentum research run",
        "created_at": datetime(2026, 7, 4, tzinfo=timezone.utc).isoformat(),
        "summary": "Seeded example run for first-time UI exploration.",
        "metrics": {"sharpe": 1.12, "annual_return": 0.21, "max_drawdown": -0.18},
        "warnings": [
            "Example data is deterministic and for UI/review workflow exploration only.",
            "Research artifact only; not investment advice.",
        ],
        "review": {
            "verdict": "PROMISING",
            "findings": [
                {
                    "check": "launch_trust_policy",
                    "severity": "warning",
                    "message": "Crypto universe is launch-limited and snapshot-derived.",
                    "detail": {"tier": "crypto_pit_snapshot_limited"},
                }
            ],
        },
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "research_note.md").write_text(
        "# Seeded Research Note\n\nResearch artifact only. Not investment advice.\n",
        encoding="utf-8",
    )
    (run_dir / "review_report.json").write_text(json.dumps(manifest["review"], indent=2), encoding="utf-8")
    (run_dir / "backtest_result.json").write_text(
        json.dumps({"metrics": manifest["metrics"], "series": {"timestamp": [], "equity": []}}, indent=2),
        encoding="utf-8",
    )
    return {"created": created, "run_ids": [EXAMPLE_RUN_ID]}
