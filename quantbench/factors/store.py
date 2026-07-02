from __future__ import annotations

import json
import re
from pathlib import Path

from quantbench.config import FACTORS_DIR
from quantbench.factors.entry import FactorEntry


VERDICT_ORDER = {"REJECTED": 0, "WEAK": 1, "PROMISING": 2, "STRONG": 3}


class FactorStore:
    def __init__(self, factors_dir: Path = FACTORS_DIR) -> None:
        self.factors_dir = Path(factors_dir)
        self.index_path = self.factors_dir / "INDEX.json"

    def save_factor(self, entry: FactorEntry, *, overwrite: bool = False) -> Path:
        self.factors_dir.mkdir(parents=True, exist_ok=True)
        path = self._entry_path(entry.name)
        if path.exists() and not overwrite:
            raise FileExistsError(f"factor already exists: {entry.name}")
        path.write_text(json.dumps(entry.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        self._write_index()
        return path

    def load_factor(self, name: str) -> FactorEntry:
        path = self._entry_path(name)
        if not path.exists():
            raise FileNotFoundError(name)
        return FactorEntry.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list_factors(
        self,
        *,
        family: str | None = None,
        asset_class: str | None = None,
        min_verdict: str | None = None,
    ) -> list[FactorEntry]:
        entries = self._load_all()
        if family:
            entries = [entry for entry in entries if entry.family == family]
        if asset_class:
            entries = [entry for entry in entries if entry.asset_class == asset_class]
        if min_verdict:
            min_rank = VERDICT_ORDER[min_verdict]
            entries = [
                entry
                for entry in entries
                if entry.source_verdict is not None and VERDICT_ORDER.get(entry.source_verdict, -1) >= min_rank
            ]
        return sorted(entries, key=lambda entry: (entry.saved_at, entry.name), reverse=True)

    def delete_factor(self, name: str) -> None:
        self._entry_path(name).unlink()
        self._write_index()

    def rebuild_index(self) -> list[dict]:
        return self._write_index()

    def _load_all(self) -> list[FactorEntry]:
        if not self.factors_dir.exists():
            return []
        return [
            FactorEntry.from_dict(json.loads(path.read_text(encoding="utf-8")))
            for path in sorted(self.factors_dir.glob("*.json"))
            if path.name != "INDEX.json"
        ]

    def _write_index(self) -> list[dict]:
        rows = [_index_row(entry) for entry in self._load_all()]
        self.factors_dir.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        return rows

    def _entry_path(self, name: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            raise ValueError("factor name may only contain letters, numbers, underscore, dash, and dot")
        return self.factors_dir / f"{name}.json"


def _index_row(entry: FactorEntry) -> dict:
    return {
        "name": entry.name,
        "family": entry.family,
        "asset_class": entry.asset_class,
        "source_run_id": entry.source_run_id,
        "source_verdict": entry.source_verdict,
        "source_sharpe": entry.source_metrics.get("sharpe"),
        "param_summary": ", ".join(f"{param['name']}={param['value']:g}" for param in entry.parameters),
        "saved_from_rejected": entry.saved_from_rejected,
        "saved_at": entry.saved_at,
    }
