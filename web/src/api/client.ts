import type { RunDetail, RunSummary } from "../types";

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

export function artifactUrl(runId: string, filename: string): string {
  return `/api/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(filename)}`;
}
