from __future__ import annotations

import ast
import difflib
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from quantbench.review.lookahead import detect_lookahead


@dataclass(frozen=True)
class FactorSpec:
    natural_language_definition: str
    formula: str
    code: str


@dataclass(frozen=True)
class ValidationReport:
    lookahead_issues: list[dict[str, Any]]
    has_shift: bool
    input_columns: list[str]
    nan_ratio: float
    coverage_ratio: float
    output_aligned: bool
    sample_head: list[dict[str, Any]]
    sample_tail: list[dict[str, Any]]
    data_quality: dict[str, Any]


@dataclass(frozen=True)
class CostEstimate:
    kind: str
    observations: int
    symbols: int | None = None
    candidates: int = 1


@dataclass(frozen=True)
class StagingPolicy:
    auto_confirm: bool = False
    force_stage: bool = False
    risk_threshold: float = 5.0
    high_cost_observations: int = 50_000
    high_cost_screen_cells: int = 50_000


@dataclass(frozen=True)
class GateDecision:
    should_stage: bool
    decision: str
    risk_score: float
    cost_score: float
    reasons: list[str]


@dataclass(frozen=True)
class StagingResult:
    code: str
    config: dict[str, Any]
    artifact: dict[str, Any]
    code_changed: bool


StagingConfirmCallback = Callable[[str, dict[str, Any], dict[str, Any]], dict[str, Any] | None]


def build_factor_spec(code: str, hypothesis: str | None = None) -> FactorSpec:
    expression = _first_return_expression(code)
    definition = (hypothesis or "").strip() or "Model-generated factor candidate."
    formula = expression or "compute(df) output"
    return FactorSpec(natural_language_definition=definition, formula=formula, code=code)


def build_validation_report(
    code: str,
    factor_values: pd.Series | pd.DataFrame,
    *,
    available_columns: list[str] | None = None,
    data_quality: Any = None,
) -> ValidationReport:
    lookahead_issues = [asdict(issue) for issue in detect_lookahead(code)]
    has_shift = _has_method_call(code, "shift")
    input_columns = _extract_input_columns(code, set(available_columns or []))
    values = _factor_series(factor_values)
    nan_ratio = round(float(values.isna().mean()), 6) if len(values) else 0.0
    coverage_ratio = round(1.0 - nan_ratio, 6) if len(values) else 0.0
    return ValidationReport(
        lookahead_issues=lookahead_issues,
        has_shift=has_shift,
        input_columns=input_columns,
        nan_ratio=nan_ratio,
        coverage_ratio=coverage_ratio,
        output_aligned=_output_aligned(factor_values),
        sample_head=_sample_records(factor_values, head=True),
        sample_tail=_sample_records(factor_values, head=False),
        data_quality=_data_quality_dict(data_quality),
    )


def should_stage(report: ValidationReport, cost: CostEstimate, policy: StagingPolicy | None = None) -> GateDecision:
    policy = policy or StagingPolicy()
    risk_score = 0.0
    cost_score = 0.0
    reasons: list[str] = []

    if policy.force_stage:
        reasons.append("force_stage")
    if policy.auto_confirm:
        return GateDecision(False, "auto_pass", 0.0, 0.0, ["auto_confirm"])

    if report.lookahead_issues:
        risk_score += 10.0
        reasons.append("lookahead")
    if not report.has_shift:
        risk_score += 1.0
        reasons.append("no_shift_detected")
    if report.nan_ratio > 0.35:
        risk_score += 3.0
        reasons.append("high_nan_ratio")
    if not report.output_aligned:
        risk_score += 5.0
        reasons.append("misaligned_output")
    if not report.input_columns:
        risk_score += 1.0
        reasons.append("no_input_columns_detected")

    cells = cost.observations * max(cost.candidates, 1)
    if cost.kind == "screen" and cells >= policy.high_cost_screen_cells:
        cost_score += 5.0
        reasons.append("high_cost")
    elif cost.observations >= policy.high_cost_observations:
        cost_score += 3.0
        reasons.append("high_cost")

    stage = policy.force_stage or risk_score >= policy.risk_threshold or cost_score >= 5.0
    return GateDecision(stage, "stopped" if stage else "auto_pass", risk_score, cost_score, reasons)


def build_staged_diff(
    *,
    original_code: str,
    final_code: str,
    original_config: dict[str, Any],
    final_config: dict[str, Any],
) -> dict[str, Any]:
    config_changes = {}
    for key in sorted(set(original_config) | set(final_config)):
        before = original_config.get(key)
        after = final_config.get(key)
        if before != after:
            config_changes[key] = {"before": before, "after": after}
    return {
        "code_changed": original_code != final_code,
        "code_diff": "\n".join(
            difflib.unified_diff(
                original_code.splitlines(),
                final_code.splitlines(),
                fromfile="model_original.py",
                tofile="staged_final.py",
                lineterm="",
            )
        ),
        "config_changes": config_changes,
    }


class StagingGate:
    def __init__(
        self,
        *,
        run_id: str,
        run_dir: Path,
        policy: StagingPolicy | None = None,
        confirm_callback: StagingConfirmCallback | None = None,
    ) -> None:
        self.run_id = run_id
        self.run_dir = Path(run_dir)
        self.policy = policy or StagingPolicy()
        self.confirm_callback = confirm_callback

    def review(
        self,
        *,
        code: str,
        factor_values: pd.Series | pd.DataFrame,
        config: dict[str, Any],
        cost: CostEstimate,
        hypothesis: str | None = None,
        available_columns: list[str] | None = None,
        data_quality: Any = None,
    ) -> StagingResult:
        factor_spec = build_factor_spec(code, hypothesis)
        report = build_validation_report(
            code,
            factor_values,
            available_columns=available_columns,
            data_quality=data_quality,
        )
        decision = should_stage(report, cost, self.policy)
        original_config = dict(config)
        final_code = code
        final_config = dict(config)
        overrides: dict[str, Any] = {}

        artifact = {
            "factor_spec": asdict(factor_spec),
            "validation_report": asdict(report),
            "gate_decision": asdict(decision),
            "overrides": overrides,
            "staged_diff": {},
        }

        if decision.should_stage:
            self._write_pending(artifact)
            overrides = self._await_overrides(artifact, original_config) or {}
            self._clear_pending()
            final_code, final_config = apply_staging_overrides(code, original_config, overrides)

        diff = build_staged_diff(
            original_code=code,
            final_code=final_code,
            original_config=original_config,
            final_config=final_config,
        )
        artifact = {
            **artifact,
            "overrides": overrides,
            "staged_diff": diff,
        }
        return StagingResult(final_code, final_config, artifact, code_changed=(final_code != code))

    def _await_overrides(self, artifact: dict[str, Any], config: dict[str, Any]) -> dict[str, Any] | None:
        if self.confirm_callback is not None:
            return self.confirm_callback(self.run_id, artifact, config)
        if not sys.stdin.isatty():
            return None
        print("\nExecution staging gate stopped before expensive backtest.")
        print(json.dumps(artifact["validation_report"], ensure_ascii=False, indent=2))
        answer = input("Continue with current factor? [y/N] ").strip().lower()
        if answer in {"y", "yes"}:
            return {}
        raise RuntimeError("run cancelled at staging gate")

    def _write_pending(self, artifact: dict[str, Any]) -> None:
        path = self.run_dir / "staging_pending.json"
        path.write_text(json.dumps(_jsonable(artifact), ensure_ascii=False, indent=2), encoding="utf-8")

    def _clear_pending(self) -> None:
        path = self.run_dir / "staging_pending.json"
        if path.exists():
            path.unlink()


def apply_staging_overrides(
    code: str,
    config: dict[str, Any],
    overrides: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    overrides = overrides or {}
    final_code = str(overrides.get("code") or code)
    final_config = dict(config)
    config_overrides = overrides.get("config") or {}
    if isinstance(config_overrides, dict):
        final_config.update(config_overrides)
    return final_code, final_config


def _first_return_expression(code: str) -> str | None:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Return) and node.value is not None:
            return ast.get_source_segment(code, node.value)
    return None


def _has_method_call(code: str, name: str) -> bool:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    return any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == name for node in ast.walk(tree))


def _extract_input_columns(code: str, available_columns: set[str]) -> list[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    columns: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and _is_df_name(node.value):
            key = _constant_string(node.slice)
            if key:
                columns.add(key)
        if isinstance(node, ast.Attribute) and _is_df_name(node.value):
            if not available_columns or node.attr in available_columns:
                columns.add(node.attr)
    return sorted(columns)


def _is_df_name(node: ast.AST) -> bool:
    return isinstance(node, ast.Name) and node.id in {"df", "data", "panel"}


def _constant_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _factor_series(values: pd.Series | pd.DataFrame) -> pd.Series:
    if isinstance(values, pd.Series):
        return values
    if "factor" in values.columns:
        return values["factor"]
    return pd.Series(dtype="float64")


def _output_aligned(values: pd.Series | pd.DataFrame) -> bool:
    if isinstance(values, pd.Series):
        return values.index.is_unique
    required = {"timestamp", "symbol", "factor"}
    if not required.issubset(values.columns):
        return False
    return not values.duplicated(["timestamp", "symbol"]).any()


def _sample_records(values: pd.Series | pd.DataFrame, *, head: bool) -> list[dict[str, Any]]:
    if isinstance(values, pd.Series):
        frame = values.rename("factor").reset_index()
    else:
        frame = values
    sample = frame.head(3) if head else frame.tail(3)
    return json.loads(sample.to_json(orient="records", date_format="iso"))


def _data_quality_dict(data_quality: Any) -> dict[str, Any]:
    if data_quality is None:
        return {}
    if hasattr(data_quality, "to_dict"):
        return data_quality.to_dict()
    if isinstance(data_quality, dict):
        return data_quality
    return {}


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        if isinstance(value, dict):
            return {str(key): _jsonable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [_jsonable(item) for item in value]
        return str(value)
