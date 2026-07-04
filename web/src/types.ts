export type RunStatus = "running" | "awaiting_confirmation" | "completed" | "failed" | "cancelled";

export type ArtifactKind =
  | "image"
  | "csv"
  | "markdown"
  | "json"
  | "yaml"
  | "code"
  | "binary"
  // Virtual kind for the Phase 4 interactive charts tab: not a real file in
  // runs/<id>/, constructed client-side (see App.tsx handleOpenCharts) so it
  // never goes through run_reader.list_artifacts on the backend.
  | "chart-dashboard";

export interface ArtifactInfo {
  filename: string;
  kind: ArtifactKind;
  size_bytes: number;
}

export type MonitoringStatus = "ok" | "watch" | "alert" | "insufficient_data";

export interface RunSummary {
  run_id: string;
  user_request: string;
  created_at: string;
  status: RunStatus;
  warnings_count: number;
  sharpe: number | null;
  monitoring_status: MonitoringStatus | null;
}

export interface RunDetail {
  run_id: string;
  user_request: string;
  created_at: string;
  status: RunStatus;
  summary: string;
  metrics: Record<string, number>;
  warnings: string[];
  artifacts: ArtifactInfo[];
  error: string | null;
  staging: StagingArtifact | null;
}

export interface SessionTurn {
  turn_index: number;
  user_message: string;
  run_id: string | null;
  summary: Record<string, unknown>;
}

export interface ResearchSession {
  session_id: string;
  created_at: string;
  turns: SessionTurn[];
}

export interface StagingArtifact {
  factor_spec?: {
    natural_language_definition?: string;
    formula?: string;
    code?: string;
  };
  validation_report?: {
    lookahead_issues?: Array<{ pattern?: string; detail?: string; line?: number | null }>;
    has_shift?: boolean;
    input_columns?: string[];
    nan_ratio?: number;
    coverage_ratio?: number;
    output_aligned?: boolean;
    sample_head?: Record<string, unknown>[];
    sample_tail?: Record<string, unknown>[];
    data_quality?: Record<string, unknown>;
  };
  gate_decision?: {
    decision?: string;
    risk_score?: number;
    cost_score?: number;
    reasons?: string[];
  };
  overrides?: Record<string, unknown>;
  staged_diff?: Record<string, unknown>;
}

export interface ExperimentRecord {
  run_id: string;
  hypothesis: string;
  created_at: string;
  status: RunStatus;
  asset_class: string;
  factor_family: string;
  cross_sectional: boolean;
  sharpe: number | null;
  annual_return: number | null;
  max_drawdown: number | null;
  turnover_annual: number | null;
  ic_mean: number | null;
  oos_sharpe: number | null;
  verdict: string | null;
  critic_verdict: string | null;
  critic_agrees: boolean | null;
  critical_count: number;
  warning_count: number;
  parent_run_id: string | null;
  error_summary: string | null;
}

export interface CompareTable {
  run_ids: string[];
  hypotheses: Record<string, string>;
  metrics: Record<string, Record<string, number | null>>;
  verdicts: Record<string, string | null>;
  findings: Record<string, Array<{ check: string; severity: string; message: string; detail: Record<string, unknown> }>>;
  returns_correlation: Record<string, Record<string, number | null>>;
}

// Mirrors BacktestResult.to_json_dict() / CrossSectionalBacktestResult.to_json_dict()
// (quantbench/engine/{vectorized_backtest,cross_sectional_backtest}.py). Fields
// are optional/absent depending on which path produced the run and, for
// `turnover`, on whether the run predates the Phase 4 backend addition -
// ChartsPanel treats every one of these as "render only if present".
export interface BacktestResultPayload {
  metrics: Record<string, number>;
  series: {
    timestamp: string[];
    returns?: number[];
    long_short_returns?: number[];
    equity_curve: number[];
    drawdown: number[];
    position?: number[];
    turnover?: number[];
    ic?: number[];
  };
  group_returns?: Record<string, number[]>;
}

// Mirrors ReviewReport.to_dict() (quantbench/review/report.py). `detail`'s
// shape depends on `check` - see the *_finding() functions in report.py for
// what each check actually populates.
export interface ReviewFindingPayload {
  check: string;
  severity: "critical" | "warning" | "info" | "pass";
  message: string;
  detail: Record<string, unknown>;
}

export interface ReviewReportPayload {
  verdict: string;
  verdict_reason: string;
  findings: ReviewFindingPayload[];
}

// Mirrors portfolio_summary.json, written by _run_portfolio_optimization
// (quantbench/agent/coordinator.py) for optimize_portfolio runs.
export interface PortfolioMethodComparison {
  weights: Record<string, number>;
  diagnostics: Record<string, unknown>;
  train_sharpe: number;
  test_sharpe: number | null;
  train_observations: number;
  test_observations: number;
}

export interface PortfolioSummary {
  parent_run_id: string | null;
  constituent_run_ids: string[];
  asset_class: string;
  selected_method: string;
  comparison_table: Record<string, PortfolioMethodComparison>;
  correlation: Record<string, Record<string, number | null>>;
  diversification_ratio: number | null;
  overlap_observations: number;
  train_test_split_index: string;
  cost_bps: number;
  max_weight: number;
}

// Mirrors DecayReport.to_dict() (quantbench/monitor/decay.py). One entry per
// check_run_decay call, oldest first - GET /api/runs/{id}/monitoring returns
// the full history under "history".
export interface DecayReportEntry {
  status: MonitoringStatus;
  checked_at: string;
  since_timestamp: string;
  original_sharpe: number;
  recent_sharpe: number | null;
  sharpe_decay_ratio: number | null;
  recent_observations: number;
  recent_max_drawdown: number | null;
  detail: string;
}

export interface MonitoringReport {
  run_id: string;
  history: DecayReportEntry[];
}

export interface ParquetPreview {
  columns: string[];
  rows: Record<string, unknown>[];
  total_rows: number;
  truncated: boolean;
}

export interface LineageResult {
  run_id: string;
  chain: ExperimentRecord[];
  edges: Array<{
    parent_run_id: string;
    child_run_id: string;
    signal_diff: string;
    metric_delta: Record<string, number | null>;
    verdict_delta: { from: string | null; to: string | null };
  }>;
  descendants: ExperimentRecord[];
}

export type RunEvent =
  | { type: "start" }
  | { type: "tool_start"; tool: string; args: Record<string, unknown> }
  | { type: "tool_end"; tool: string; result: unknown }
  | { type: "staging"; artifact: StagingArtifact; config: Record<string, unknown> }
  | { type: "memory"; message: string; events: Record<string, unknown>[] }
  | { type: "final"; summary: string }
  | { type: "cancelled" }
  | { type: "error"; message: string };
