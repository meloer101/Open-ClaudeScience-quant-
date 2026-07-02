export type RunStatus = "running" | "completed" | "failed";

export type ArtifactKind =
  | "image"
  | "csv"
  | "markdown"
  | "json"
  | "yaml"
  | "code"
  | "binary";

export interface ArtifactInfo {
  filename: string;
  kind: ArtifactKind;
  size_bytes: number;
}

export interface RunSummary {
  run_id: string;
  user_request: string;
  created_at: string;
  status: RunStatus;
  warnings_count: number;
  sharpe: number | null;
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
  | { type: "final"; summary: string }
  | { type: "error"; message: string };
