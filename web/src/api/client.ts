import type { CompareTable, ExperimentRecord, LineageResult, RunDetail, RunSummary } from "../types";

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
