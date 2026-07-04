from __future__ import annotations

from pathlib import Path
from typing import Any

from quantbench.api import run_reader
from quantbench.data.cache import file_sha256


def audit_run_data_retention(run_id: str) -> dict[str, Any]:
    manifest = run_reader.read_manifest(run_id)
    if manifest is None:
        raise FileNotFoundError(run_id)
    slices = list(manifest.get("data_slices") or [])
    missing: list[str] = []
    drifted: list[dict[str, str]] = []
    checked = 0
    for item in slices:
        path = item.get("path")
        expected = item.get("content_hash")
        if not path or not expected:
            drifted.append({"path": str(path or ""), "reason": "missing path/hash metadata"})
            continue
        file_path = Path(path)
        if not file_path.exists():
            missing.append(str(file_path))
            continue
        checked += 1
        actual = file_sha256(file_path)
        if actual != expected:
            drifted.append({"path": str(file_path), "expected": str(expected), "actual": actual})
    status = "ok" if not missing and not drifted else "failed"
    if not slices:
        status = "not_applicable"
    return {
        "run_id": run_id,
        "status": status,
        "slices_total": len(slices),
        "slices_checked": checked,
        "missing": missing,
        "drifted": drifted,
    }
