from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from quantbench.api import run_reader
from quantbench.library.record import ExperimentRecord, build_record


@dataclass(frozen=True)
class ExperimentIndex:
    records: list[ExperimentRecord]

    @classmethod
    def build(cls) -> "ExperimentIndex":
        records = [build_record(run_id) for run_id in run_reader.list_run_ids()]
        return cls(records=records)

    def get(self, run_id: str) -> ExperimentRecord:
        for record in self.records:
            if record.run_id == run_id:
                return record
        raise KeyError(run_id)

    def filter(
        self,
        *,
        verdicts: set[str] | None = None,
        asset_class: str | None = None,
        factor_family: str | None = None,
        min_sharpe: float | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
    ) -> "ExperimentIndex":
        records = self.records
        if verdicts:
            normalized = {item.upper() for item in verdicts}
            records = [record for record in records if (record.verdict or "").upper() in normalized]
        if asset_class:
            records = [record for record in records if record.asset_class == asset_class]
        if factor_family:
            records = [record for record in records if record.factor_family == factor_family]
        if min_sharpe is not None:
            records = [record for record in records if record.sharpe is not None and record.sharpe >= min_sharpe]
        if created_after:
            records = [record for record in records if _date_key(record.created_at) >= _date_key(created_after)]
        if created_before:
            records = [record for record in records if _date_key(record.created_at) <= _date_key(created_before)]
        return ExperimentIndex(records=list(records))

    def sort(self, field: str, *, descending: bool = True) -> "ExperimentIndex":
        def key(record: ExperimentRecord):
            value = getattr(record, field, None)
            missing = value is None or value == ""
            normalized = _date_key(value) if field == "created_at" and isinstance(value, str) else value
            return (missing, normalized, record.run_id)

        present = [record for record in self.records if getattr(record, field, None) not in (None, "")]
        missing = [record for record in self.records if getattr(record, field, None) in (None, "")]
        return ExperimentIndex(records=sorted(present, key=key, reverse=descending) + sorted(missing, key=lambda r: r.run_id))

    def to_dicts(self) -> list[dict]:
        return [record.to_dict() for record in self.records]


def parse_csv_set(value: str | None) -> set[str] | None:
    if not value:
        return None
    return {item.strip() for item in value.split(",") if item.strip()}


def _date_key(value: str) -> datetime:
    if not value:
        return datetime.min
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return datetime.min
