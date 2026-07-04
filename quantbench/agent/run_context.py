from dataclasses import dataclass
from pathlib import Path
from typing import Any

from quantbench.data.universe import UniverseDefinition
from quantbench.engine.execution import ExecutionConfig
from quantbench.review import CriticReport, ReviewReport
from quantbench.skills.data_quality import DataQualityReport


@dataclass
class RunResult:
    run_id: str
    run_dir: Path
    metrics: dict[str, float]
    warnings: list[str]
    summary: str


class RunCancelled(Exception):
    """Raised inside execute()/execute_fork() when the caller's cancel_event
    fires. Callers (RunManager) catch this to mark the run "cancelled" instead
    of "failed" and to stop the tool-use loop before its next expensive LLM
    call, rather than letting a stuck run spin for up to MAX_STEPS."""

    def __init__(self, run_id: str):
        super().__init__(f"run {run_id} was cancelled")
        self.run_id = run_id


class _RunContext:
    """Mutable state threaded through one Coordinator.run() call."""

    def __init__(self) -> None:
        self.data_path: Path | None = None
        self.data_df = None
        self.cache_meta: dict[str, Any] | None = None
        self.last_metrics: dict[str, float] | None = None
        self.signal_code: str | None = None
        self.universe: UniverseDefinition | None = None
        self.panel_df = None
        self.funding_df = None
        self.funding_meta: dict[str, Any] | None = None
        self.data_quality: DataQualityReport | None = None
        self.cross_sectional = False
        self.warnings: list[str] = []
        self.fetch_params: dict[str, str] | None = None
        self.review_report: ReviewReport | None = None
        self.critic_report: CriticReport | None = None
        self.injected_skills: list[str] = []
        self.cost_bps: float | None = None
        self.execution: ExecutionConfig | None = None
        self.cost_model = "fixed_bps"
        self.borrow_model = "not_applied"
        self.neutralize: list[str] = []
        self.capacity_curve: list[dict[str, Any]] = []
        self.long_short_contribution: dict[str, Any] = {}
        self.neutralization_comparison: dict[str, Any] = {}
        self.screened = False
        self.delegations: list[dict[str, Any]] = []
        self.sandbox_usage: list[Any] = []
        self.mcp_calls: list[dict[str, Any]] = []
        self.staging: dict[str, Any] | None = None
        self.staging_confirm = None
        self.memory_default_facts: list[Any] = []
        self.applied_memory_defaults: list[dict[str, Any]] = []
        self.memory_events: list[dict[str, Any]] = []
