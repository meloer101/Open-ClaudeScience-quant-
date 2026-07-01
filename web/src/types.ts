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
