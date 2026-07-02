from __future__ import annotations

from typing import Any

from quantbench.api import run_reader


def build_fork_config(parent_run_id: str, modification_request: str) -> dict[str, Any]:
    config = run_reader.read_config(parent_run_id)
    if config is None:
        raise FileNotFoundError(f"parent config not found: {parent_run_id}")
    manifest = run_reader.read_manifest(parent_run_id) or {}
    signal_path = run_reader.run_dir_for(parent_run_id) / "signal.py"
    parent_signal_code = signal_path.read_text(encoding="utf-8") if signal_path.exists() else ""

    return {
        "parent_run_id": parent_run_id,
        "modification_request": modification_request,
        "hypothesis": config.get("hypothesis") or manifest.get("user_request") or "",
        "data_path": config.get("data_path"),
        "universe": config.get("universe"),
        "date_range": config.get("date_range"),
        "timeframe": config.get("timeframe"),
        "cache": config.get("cache"),
        "parent_data_hash": manifest.get("data_hash"),
        "parent_signal_code": parent_signal_code,
    }
