import type {
  BacktestResultPayload,
  CompareTable,
  ExperimentRecord,
  LineageResult,
  ParquetPreview,
  ReviewReportPayload,
  RunDetail,
  RunSummary,
} from "../types";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${body}`);
  }
  return response.json() as Promise<T>;
}

export function listRuns(): Promise<RunSummary[]> {
  return request<RunSummary[]>("/runs");
}

export function getRun(runId: string): Promise<RunDetail> {
  return request<RunDetail>(`/runs/${encodeURIComponent(runId)}`);
}

export function getRunStatus(runId: string): Promise<{ status: string }> {
  return request(`/runs/${encodeURIComponent(runId)}/status`);
}

export function createRun(userRequest: string): Promise<{ run_id: string; status: string }> {
  return request("/runs", {
    method: "POST",
    body: JSON.stringify({ request: userRequest }),
  });
}

export interface LibraryFilters {
  verdict?: string;
  asset?: string;
  factor_family?: string;
  min_sharpe?: string;
  sort?: string;
}

export function listLibrary(filters: LibraryFilters = {}): Promise<ExperimentRecord[]> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value);
  }
  const query = params.toString();
  return request<ExperimentRecord[]>(`/library${query ? `?${query}` : ""}`);
}

export function compareRuns(runIds: string[]): Promise<CompareTable> {
  return request<CompareTable>(`/compare?run_ids=${encodeURIComponent(runIds.join(","))}`);
}

export function getLineage(runId: string): Promise<LineageResult> {
  return request<LineageResult>(`/runs/${encodeURIComponent(runId)}/lineage`);
}

export function forkRun(runId: string, modification: string): Promise<{ run_id: string; status: string }> {
  return request(`/runs/${encodeURIComponent(runId)}/fork`, {
    method: "POST",
    body: JSON.stringify({ modification }),
  });
}

export function artifactUrl(runId: string, filename: string): string {
  return `/api/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(filename)}`;
}

export function runEventsUrl(runId: string): string {
  return `/api/runs/${encodeURIComponent(runId)}/events`;
}

async function fetchArtifactJson<T>(runId: string, filename: string): Promise<T | null> {
  const response = await fetch(artifactUrl(runId, filename));
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json() as Promise<T>;
}

export async function getBacktestResult(runId: string): Promise<BacktestResultPayload | null> {
  // Not a direct artifact-by-filename fetch: some historical cross-sectional
  // runs wrote a different filename before it was unified with the
  // single-symbol path (see run_reader.read_backtest_result on the backend).
  // This endpoint resolves either name so the frontend never has to guess.
  const response = await fetch(`/api/runs/${encodeURIComponent(runId)}/backtest-result`);
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json() as Promise<BacktestResultPayload>;
}

export function getReviewReport(runId: string): Promise<ReviewReportPayload | null> {
  return fetchArtifactJson<ReviewReportPayload>(runId, "review_report.json");
}

export function previewParquet(runId: string, filename: string): Promise<ParquetPreview> {
  return request<ParquetPreview>(`/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(filename)}/preview`);
}
