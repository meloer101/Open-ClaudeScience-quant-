"""Read-only access to the runs/ artifact directory. No computation here -
this only reads files Coordinator already wrote."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from quantbench.config import RUNS_DIR

_RUN_ID_TIMESTAMP = re.compile(r"^run_(\d{8})_(\d{6})_")


def created_at_from_run_id(run_id: str) -> str:
    """Derive created_at from the run_id itself (run_YYYYMMDD_HHMMSS_xxxx).

    Used as a fallback for runs still in progress, which have no manifest.json
    yet - without this, an in-progress run's created_at is empty and sorts
    into an "Unknown" date group in the UI instead of "Today"."""
    match = _RUN_ID_TIMESTAMP.match(run_id)
    if not match:
        return ""
    date_part, time_part = match.groups()
    try:
        dt = datetime.strptime(f"{date_part}{time_part}", "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return ""
    return dt.isoformat()

ARTIFACT_KIND_BY_EXT = {
    ".png": "image",
    ".csv": "csv",
    ".md": "markdown",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".py": "code",
}

# Internal bookkeeping files, not shown as user-facing generated artifacts.
_HIDDEN_FILES = {"manifest.json", "config.yaml", "conversation.json", "error.json", "request.txt"}


def list_run_ids() -> list[str]:
    if not RUNS_DIR.exists():
        return []
    return sorted(
        (p.name for p in RUNS_DIR.iterdir() if p.is_dir() and p.name.startswith("run_")),
        reverse=True,
    )


def run_dir_for(run_id: str) -> Path:
    return RUNS_DIR / run_id


def get_status(run_id: str) -> str:
    run_dir = run_dir_for(run_id)
    if not run_dir.exists():
        raise FileNotFoundError(run_id)
    if (run_dir / "manifest.json").exists():
        return "completed"
    if (run_dir / "error.json").exists():
        return "failed"
    return "running"


_METRIC_TOOLS = {"run_signal_backtest", "run_cross_sectional_backtest"}


def read_manifest(run_id: str) -> dict[str, Any] | None:
    """Read manifest.json, backfilling `summary`/`metrics` for runs recorded
    before those fields existed on the manifest (derived from `steps` and the
    conversation log so older runs still render correctly in the API/UI)."""
    path = run_dir_for(run_id) / "manifest.json"
    if not path.exists():
        return None
    manifest = json.loads(path.read_text(encoding="utf-8"))

    if not manifest.get("summary"):
        manifest["summary"] = _derive_summary(run_id, manifest)
    if not manifest.get("metrics"):
        manifest["metrics"] = _derive_metrics(manifest)
    return manifest


def _derive_summary(run_id: str, manifest: dict[str, Any]) -> str:
    log_name = manifest.get("conversation_log")
    if not log_name:
        return ""
    log_path = run_dir_for(run_id) / log_name
    if not log_path.exists():
        return ""
    messages = json.loads(log_path.read_text(encoding="utf-8"))
    for message in reversed(messages):
        if message.get("role") == "assistant" and not message.get("tool_calls") and message.get("content"):
            return message["content"]
    return ""


def _derive_metrics(manifest: dict[str, Any]) -> dict[str, Any]:
    for step in reversed(manifest.get("steps", [])):
        if step.get("tool") in _METRIC_TOOLS and isinstance(step.get("result"), dict):
            return {k: v for k, v in step["result"].items() if k != "warnings" and not isinstance(v, dict)}
    return {}


def read_config(run_id: str) -> dict[str, Any] | None:
    path = run_dir_for(run_id) / "config.yaml"
    if not path.exists():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def read_user_request(run_id: str) -> str:
    """Fallback for runs still in progress: their request text is written to
    request.txt immediately on creation, before manifest.json exists."""
    path = run_dir_for(run_id) / "request.txt"
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def read_error(run_id: str) -> str | None:
    path = run_dir_for(run_id) / "error.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("traceback")


# Cross-sectional runs used to write this result under a different filename
# than the single-symbol path ("cross_sectional_backtest_result.json" vs
# "backtest_result.json") before the two were unified onto one canonical name.
# Historical run directories on disk still have the old name and are valid
# project history - readers must keep resolving it, not just new writers.
_LEGACY_CROSS_SECTIONAL_BACKTEST_RESULT_FILENAME = "cross_sectional_backtest_result.json"


def read_backtest_result(run_id: str) -> dict[str, Any] | None:
    run_dir = run_dir_for(run_id)
    for filename in ("backtest_result.json", _LEGACY_CROSS_SECTIONAL_BACKTEST_RESULT_FILENAME):
        path = run_dir / filename
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    return None


PARQUET_PREVIEW_ROW_LIMIT = 200


def preview_parquet(run_id: str, filename: str) -> dict[str, Any] | None:
    """First PARQUET_PREVIEW_ROW_LIMIT rows of a run's .parquet artifact as
    JSON-safe records, mirroring the existing "first 200 rows, download for
    the rest" convention the web CSV viewer already uses (ArtifactInspector.tsx
    CsvTable). Returns None if the file doesn't exist so the caller can 404.

    Uses pyarrow directly rather than pandas.read_parquet(path).head(n): a
    universe panel.parquet can hold years of daily bars for hundreds of
    symbols, and reading the whole thing into memory just to preview 200 rows
    would scale with total file size instead of the preview size. Row count
    comes from Parquet metadata (no data read at all), and only as many row
    groups as needed to reach the row limit are decoded."""
    path = run_dir_for(run_id) / filename
    if not path.is_file():
        return None

    parquet_file = pq.ParquetFile(path)
    total_rows = parquet_file.metadata.num_rows
    columns = [str(name) for name in parquet_file.schema_arrow.names]

    batches = []
    collected_rows = 0
    for batch in parquet_file.iter_batches(batch_size=PARQUET_PREVIEW_ROW_LIMIT):
        batches.append(batch)
        collected_rows += batch.num_rows
        if collected_rows >= PARQUET_PREVIEW_ROW_LIMIT:
            break

    if batches:
        preview = pa.Table.from_batches(batches).to_pandas().head(PARQUET_PREVIEW_ROW_LIMIT)
    else:
        preview = pd.DataFrame(columns=columns)
    records = json.loads(preview.to_json(orient="records", date_format="iso"))
    return {
        "columns": columns,
        "rows": records,
        "total_rows": total_rows,
        "truncated": total_rows > PARQUET_PREVIEW_ROW_LIMIT,
    }


def list_artifacts(run_id: str) -> list[dict[str, Any]]:
    run_dir = run_dir_for(run_id)
    if not run_dir.exists():
        return []
    items = []
    for path in sorted(run_dir.iterdir()):
        if path.is_dir() or path.name in _HIDDEN_FILES:
            continue
        kind = ARTIFACT_KIND_BY_EXT.get(path.suffix, "binary")
        items.append({"filename": path.name, "kind": kind, "size_bytes": path.stat().st_size})
    return items
