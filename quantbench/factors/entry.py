from __future__ import annotations

import ast
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from quantbench.api import run_reader
from quantbench.factors.parametrize import extract_parameters
from quantbench.library.record import build_record


class RejectedFactorError(ValueError):
    pass


@dataclass(frozen=True)
class FactorEntry:
    name: str
    family: str
    asset_class: str
    code: str
    parameters: list[dict[str, Any]]
    source_run_id: str
    source_verdict: str | None
    source_metrics: dict[str, Any]
    source_findings: list[dict[str, Any]]
    saved_from_rejected: bool
    saved_at: str
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "FactorEntry":
        return cls(
            name=str(payload["name"]),
            family=str(payload.get("family") or "unclassified"),
            asset_class=str(payload.get("asset_class") or "unknown"),
            code=str(payload["code"]),
            parameters=list(payload.get("parameters") or []),
            source_run_id=str(payload["source_run_id"]),
            source_verdict=payload.get("source_verdict"),
            source_metrics=dict(payload.get("source_metrics") or {}),
            source_findings=list(payload.get("source_findings") or []),
            saved_from_rejected=bool(payload.get("saved_from_rejected")),
            saved_at=str(payload.get("saved_at") or ""),
            notes=str(payload.get("notes") or ""),
        )


def build_entry_from_run(run_id: str, name: str, *, force: bool = False, notes: str = "") -> FactorEntry:
    run_dir = run_reader.run_dir_for(run_id)
    signal_path = run_dir / "signal.py"
    if not signal_path.exists():
        raise FileNotFoundError(f"{run_id}/signal.py")

    manifest = run_reader.read_manifest(run_id) or {}
    review = manifest.get("review") or _read_json(run_dir / "review_report.json") or {}
    verdict = review.get("verdict")
    if verdict == "REJECTED" and not force:
        raise RejectedFactorError(f"run {run_id} has REJECTED verdict; pass --force to save it anyway")

    record = build_record(run_id)
    code = _extract_compute_source(signal_path.read_text(encoding="utf-8"))
    return FactorEntry(
        name=name,
        family=record.factor_family,
        asset_class=record.asset_class,
        code=code,
        parameters=extract_parameters(code),
        source_run_id=run_id,
        source_verdict=verdict,
        source_metrics=dict(manifest.get("metrics") or {}),
        source_findings=[
            finding
            for finding in (review.get("findings") or [])
            if str(finding.get("severity", "")).lower() in {"critical", "warning"}
        ],
        saved_from_rejected=verdict == "REJECTED",
        saved_at=datetime.now(timezone.utc).isoformat(),
        notes=notes,
    )


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def _extract_compute_source(source: str) -> str:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "compute":
            segment = ast.get_source_segment(source, node)
            if segment:
                return segment.rstrip() + "\n"
    raise ValueError("signal.py must define def compute(...)")
