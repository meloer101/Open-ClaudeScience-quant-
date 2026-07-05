import type {
  AskPaperResponse,
  BacktestResultPayload,
  CompareTable,
  DecayReportEntry,
  ExperimentRecord,
  LineageResult,
  MonitoringReport,
  PaperDetail,
  PaperSummary,
  ParquetPreview,
  PortfolioSummary,
  ResearchSession,
  ReviewReportPayload,
  RunDetail,
  RunSummary,
} from "../types";

const API_BASE = import.meta.env.VITE_QUANTBENCH_API_BASE ?? "/api";
const API_TOKEN = import.meta.env.VITE_QUANTBENCH_API_TOKEN ?? "";

function authHeaders(extra?: HeadersInit): Headers {
  const headers = new Headers(extra);
  headers.set("Content-Type", "application/json");
  if (API_TOKEN) headers.set("X-QuantBench-Token", API_TOKEN);
  return headers;
}

function authUrl(path: string): string {
  if (!API_TOKEN) return path;
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}token=${encodeURIComponent(API_TOKEN)}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: authHeaders(init?.headers),
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

export interface CostEstimate {
  estimated_tokens: number;
  estimated_usd: number;
  coordinator_calls: number;
  critic_calls: number;
  note: string;
}

export function estimateRunCost(userRequest: string): Promise<CostEstimate> {
  return request("/runs/estimate-cost", {
    method: "POST",
    body: JSON.stringify({ request: userRequest }),
  });
}

export function createSession(): Promise<{ session_id: string; created_at: string }> {
  return request("/sessions", { method: "POST" });
}

export function getSession(sessionId: string): Promise<ResearchSession> {
  return request<ResearchSession>(`/sessions/${encodeURIComponent(sessionId)}`);
}

export function createSessionTurn(sessionId: string, userMessage: string): Promise<{ run_id: string; status: string }> {
  return request(`/sessions/${encodeURIComponent(sessionId)}/turns`, {
    method: "POST",
    body: JSON.stringify({ user_message: userMessage }),
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

export function cancelRun(runId: string): Promise<{ status: string }> {
  return request(`/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST" });
}

export function confirmStaging(runId: string, overrides: Record<string, unknown>): Promise<{ status: string }> {
  return request(`/runs/${encodeURIComponent(runId)}/staging/confirm`, {
    method: "POST",
    body: JSON.stringify({ overrides }),
  });
}

export function forkRun(runId: string, modification: string): Promise<{ run_id: string; status: string }> {
  return request(`/runs/${encodeURIComponent(runId)}/fork`, {
    method: "POST",
    body: JSON.stringify({ modification }),
  });
}

// --- Literature (GAP 4.3) ---

export function listPapers(): Promise<PaperSummary[]> {
  return request<PaperSummary[]>("/literature");
}

export function ingestPaper(source: string): Promise<PaperSummary> {
  return request<PaperSummary>("/literature/ingest", {
    method: "POST",
    body: JSON.stringify({ source }),
  });
}

export async function uploadPaper(file: File): Promise<PaperSummary> {
  const body = new FormData();
  body.append("file", file);
  const response = await fetch(`${API_BASE}/literature/ingest/upload`, {
    method: "POST",
    headers: API_TOKEN ? { "X-QuantBench-Token": API_TOKEN } : undefined,
    body,
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${await response.text()}`);
  return response.json() as Promise<PaperSummary>;
}

export function getPaper(paperId: string): Promise<PaperDetail> {
  return request<PaperDetail>(`/literature/${encodeURIComponent(paperId)}`);
}

export function paperPdfUrl(paperId: string): string {
  return authUrl(`${API_BASE}/literature/${encodeURIComponent(paperId)}/pdf`);
}

export function askPaper(
  paperId: string,
  body: { selection: string; question: string; page: number | null },
): Promise<AskPaperResponse> {
  return request<AskPaperResponse>(`/literature/${encodeURIComponent(paperId)}/ask`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function reproducePaper(
  paperId: string,
  body: { request?: string | null; selection?: string | null; page?: number | null },
): Promise<{ run_id: string; status: string }> {
  return request(`/literature/${encodeURIComponent(paperId)}/reproduce`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function artifactUrl(runId: string, filename: string): string {
  return authUrl(`${API_BASE}/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(filename)}`);
}

export function runEventsUrl(runId: string): string {
  return authUrl(`${API_BASE}/runs/${encodeURIComponent(runId)}/events`);
}

async function fetchArtifactJson<T>(runId: string, filename: string): Promise<T | null> {
  const response = await fetch(artifactUrl(runId, filename), {
    headers: API_TOKEN ? { "X-QuantBench-Token": API_TOKEN } : undefined,
  });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json() as Promise<T>;
}

export async function getBacktestResult(runId: string): Promise<BacktestResultPayload | null> {
  // Not a direct artifact-by-filename fetch: some historical cross-sectional
  // runs wrote a different filename before it was unified with the
  // single-symbol path (see run_reader.read_backtest_result on the backend).
  // This endpoint resolves either name so the frontend never has to guess.
  const response = await fetch(authUrl(`${API_BASE}/runs/${encodeURIComponent(runId)}/backtest-result`), {
    headers: API_TOKEN ? { "X-QuantBench-Token": API_TOKEN } : undefined,
  });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json() as Promise<BacktestResultPayload>;
}

export function getReviewReport(runId: string): Promise<ReviewReportPayload | null> {
  return fetchArtifactJson<ReviewReportPayload>(runId, "review_report.json");
}

export async function getPortfolioSummary(runId: string): Promise<PortfolioSummary | null> {
  const response = await fetch(authUrl(`${API_BASE}/runs/${encodeURIComponent(runId)}/portfolio`), {
    headers: API_TOKEN ? { "X-QuantBench-Token": API_TOKEN } : undefined,
  });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json() as Promise<PortfolioSummary>;
}

export function previewParquet(runId: string, filename: string): Promise<ParquetPreview> {
  return request<ParquetPreview>(`/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(filename)}/preview`);
}

export async function getMonitoringReport(runId: string): Promise<MonitoringReport | null> {
  const response = await fetch(authUrl(`${API_BASE}/runs/${encodeURIComponent(runId)}/monitoring`), {
    headers: API_TOKEN ? { "X-QuantBench-Token": API_TOKEN } : undefined,
  });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json() as Promise<MonitoringReport>;
}

export function triggerMonitoringCheck(
  runId: string,
): Promise<DecayReportEntry | { error: string } | { skipped: string; verdict: string | null }> {
  return request(`/runs/${encodeURIComponent(runId)}/monitoring/check`, { method: "POST" });
}

// --- Config ---

export interface ConfigStatus {
  llm_key_configured: boolean;
  model: string;
  key_env: string;
}

export function getConfigStatus(): Promise<ConfigStatus> {
  return request("/config/status");
}

export function setLlmConfig(model: string, apiKey: string): Promise<{ status: string }> {
  return request("/config/llm-key", {
    method: "POST",
    body: JSON.stringify({ model, api_key: apiKey }),
  });
}
