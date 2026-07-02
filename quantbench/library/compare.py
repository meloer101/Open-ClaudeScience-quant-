from __future__ import annotations

from typing import Any

from quantbench.api import run_reader


METRIC_FIELDS = ("sharpe", "annual_return", "max_drawdown", "turnover_annual", "ic_mean")


def compare_runs(run_ids: list[str]) -> dict[str, Any]:
    metrics = {field: {} for field in METRIC_FIELDS}
    verdicts: dict[str, str | None] = {}
    findings: dict[str, list[dict[str, Any]]] = {}
    hypotheses: dict[str, str] = {}

    for run_id in run_ids:
        manifest = run_reader.read_manifest(run_id) or {}
        config = run_reader.read_config(run_id) or {}
        run_metrics = manifest.get("metrics") or {}
        review = manifest.get("review") or {}
        hypotheses[run_id] = config.get("hypothesis") or manifest.get("user_request") or run_reader.read_user_request(run_id)
        verdicts[run_id] = review.get("verdict")
        for field in METRIC_FIELDS:
            metrics[field][run_id] = run_metrics.get(field)
        findings[run_id] = [
            finding
            for finding in (review.get("findings") or [])
            if str(finding.get("severity", "")).lower() in {"critical", "warning"}
        ]

    return {"run_ids": run_ids, "hypotheses": hypotheses, "metrics": metrics, "verdicts": verdicts, "findings": findings}
