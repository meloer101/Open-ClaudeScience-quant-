import { useState } from "react";
import { MonitoringStatusBadge } from "./MonitoringStatusBadge";
import type { ExperimentRecord, PaperSummary, RunSummary } from "../types";

interface SidebarProps {
  runs: RunSummary[];
  libraryRecords: ExperimentRecord[];
  papers: PaperSummary[];
  selectedRunId: string | null;
  activePaperId: string | null;
  onSelect: (runId: string) => void;
  onOpenPaper: (paperId: string) => void;
  onImportPaper: (source: string) => Promise<void>;
  onUploadPaper?: (file: File) => Promise<void>;
  onNew: () => void;
  compareRunIds: string[];
  onToggleCompare: (runId: string) => void;
  onOpenCompare: () => void;
  libraryFilters: { verdict: string; asset: string; sort: string };
  onLibraryFiltersChange: (filters: { verdict: string; asset: string; sort: string }) => void;
  isLoading: boolean;
  width: number;
  onToggleCollapse: () => void;
}

export function SidebarToggleIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" fill="none" className={className} aria-hidden="true">
      <rect x="1.5" y="2.5" width="13" height="11" rx="1.5" stroke="currentColor" strokeWidth="1.2" />
      <line x1="6" y1="2.5" x2="6" y2="13.5" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  );
}

function LiteratureSection({
  papers,
  activePaperId,
  onOpenPaper,
  onImportPaper,
  onUploadPaper,
}: {
  papers: PaperSummary[];
  activePaperId: string | null;
  onOpenPaper: (paperId: string) => void;
  onImportPaper: (source: string) => Promise<void>;
  onUploadPaper?: (file: File) => Promise<void>;
}) {
  const [source, setSource] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    const value = source.trim();
    if (!value || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onImportPaper(value);
      setSource("");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !onUploadPaper || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onUploadPaper(file);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  };

  return (
    <div className="px-3 pb-3 border-b border-warm-100">
      <div className="text-xs font-medium text-warm-500 mb-2 px-1">Literature</div>
      <div className="flex gap-1.5 mb-2">
        <input
          value={source}
          onChange={(e) => setSource(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void submit();
          }}
          placeholder="arXiv URL / ID"
          className="flex-1 min-w-0 text-xs border border-warm-150 rounded-md bg-white px-1.5 py-1"
        />
        <button
          onClick={() => void submit()}
          disabled={busy || !source.trim()}
          className="text-xs px-2 py-1 rounded-md bg-warm-900 text-white disabled:bg-warm-150 disabled:text-warm-500"
        >
          {busy ? "…" : "导入"}
        </button>
        {onUploadPaper && (
          <label className="text-xs px-2 py-1 rounded-md bg-warm-100 text-warm-700 hover:bg-warm-200 cursor-pointer">
            PDF
            <input type="file" accept=".pdf" onChange={handleFileUpload} className="hidden" />
          </label>
        )}
      </div>
      {error && <div className="text-[10px] text-danger-600 mb-1 px-1 break-words">{error}</div>}
      {papers.length > 0 && (
        <div className="max-h-40 overflow-y-auto border border-warm-100 rounded-md bg-white">
          {papers.map((paper) => (
            <button
              key={paper.paper_id}
              onClick={() => onOpenPaper(paper.paper_id)}
              className={`w-full text-left px-2 py-1.5 border-b border-warm-50 last:border-b-0 text-xs ${
                paper.paper_id === activePaperId ? "bg-warm-50" : ""
              }`}
            >
              <span className="block truncate text-warm-800">{paper.title}</span>
              <span className="text-warm-400">
                {paper.source_kind}
                {paper.arxiv_id ? ` · ${paper.arxiv_id}` : ""} · {paper.n_pages}p
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function dateGroupLabel(createdAt: string): string {
  if (!createdAt) return "Unknown";
  const date = new Date(createdAt);
  const now = new Date();
  const isToday = date.toDateString() === now.toDateString();
  if (isToday) return "Today";
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return "Yesterday";
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function StatusDot({ status }: { status: RunSummary["status"] }) {
  if (status === "running") {
    return <span className="inline-block w-1.5 h-1.5 rounded-full bg-warn-200 animate-pulse" aria-label={status} />;
  }
  if (status === "failed") {
    return <span className="inline-block w-1.5 h-1.5 rounded-full bg-danger-400" aria-label={status} />;
  }
  return <span className="inline-block w-1.5 h-1.5 rounded-full border border-warm-300" aria-label={status} />;
}

function VerdictBadge({ verdict }: { verdict: string | null }) {
  const tone =
    verdict === "STRONG"
      ? "bg-success-50 text-success-600"
      : verdict === "PROMISING"
        ? "bg-accent-50 text-accent-800"
        : verdict === "REJECTED"
          ? "bg-danger-50 text-danger-600"
          : "bg-warm-100 text-warm-600";
  return <span className={`px-1.5 py-0.5 rounded text-[10px] leading-none ${tone}`}>{verdict ?? "NONE"}</span>;
}

function CriticDisagreementBadge({ agrees }: { agrees: boolean | null }) {
  if (agrees !== false) return null;
  return <span className="px-1.5 py-0.5 rounded text-[10px] leading-none bg-danger-50 text-danger-600">CRITIC</span>;
}

function fmt(value: number | null): string {
  if (value === null) return "";
  return value.toFixed(2);
}

export function Sidebar({
  runs,
  libraryRecords,
  papers,
  selectedRunId,
  activePaperId,
  onSelect,
  onOpenPaper,
  onImportPaper,
  onUploadPaper,
  onNew,
  compareRunIds,
  onToggleCompare,
  onOpenCompare,
  libraryFilters,
  onLibraryFiltersChange,
  isLoading,
  width,
  onToggleCollapse,
}: SidebarProps) {
  const groups = new Map<string, RunSummary[]>();
  for (const run of runs) {
    const label = dateGroupLabel(run.created_at);
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label)!.push(run);
  }

  return (
    <div className="shrink-0 bg-warm-25 h-full flex flex-col overflow-hidden" style={{ width }}>
      <div className="px-3 pt-4 pb-3">
        <div className="flex items-center justify-between mb-3 px-1">
          <div className="font-medium text-warm-900">QuantBench</div>
          <button
            type="button"
            onClick={onToggleCollapse}
            aria-label="收起侧栏"
            title="收起侧栏"
            className="p-1 rounded-md text-warm-400 hover:bg-warm-100 hover:text-warm-600 transition-colors"
          >
            <SidebarToggleIcon className="w-4 h-4" />
          </button>
        </div>
        <button
          onClick={onNew}
          className="w-full text-left text-sm px-2.5 py-1.5 rounded-md text-warm-700 hover:bg-warm-100 transition-colors flex items-center gap-1.5"
        >
          <span className="text-warm-400">+</span>
          New
        </button>
      </div>
      <div className="px-3 pb-3 border-b border-warm-100">
        <div className="text-xs font-medium text-warm-500 mb-2 px-1">Experiment Library</div>
        <div className="grid grid-cols-2 gap-1.5 mb-2">
          <select
            value={libraryFilters.verdict}
            onChange={(event) => onLibraryFiltersChange({ ...libraryFilters, verdict: event.target.value })}
            className="text-xs border border-warm-150 rounded-md bg-white px-1.5 py-1"
            aria-label="Verdict filter"
          >
            <option value="">All verdicts</option>
            <option value="STRONG,PROMISING">Strong + promising</option>
            <option value="WEAK">Weak</option>
            <option value="REJECTED">Rejected</option>
          </select>
          <select
            value={libraryFilters.asset}
            onChange={(event) => onLibraryFiltersChange({ ...libraryFilters, asset: event.target.value })}
            className="text-xs border border-warm-150 rounded-md bg-white px-1.5 py-1"
            aria-label="Asset filter"
          >
            <option value="">All assets</option>
            <option value="equity">Equity</option>
            <option value="crypto">Crypto</option>
            <option value="unknown">Unknown</option>
          </select>
        </div>
        <select
          value={libraryFilters.sort}
          onChange={(event) => onLibraryFiltersChange({ ...libraryFilters, sort: event.target.value })}
          className="w-full text-xs border border-warm-150 rounded-md bg-white px-1.5 py-1 mb-2"
          aria-label="Sort field"
        >
          <option value="created_at">Newest</option>
          <option value="sharpe">Sharpe</option>
          <option value="oos_sharpe">OOS Sharpe</option>
          <option value="warning_count">Warnings</option>
        </select>
        <div className="max-h-64 overflow-y-auto border border-warm-100 rounded-md bg-white">
          {libraryRecords.map((record) => (
            <div
              key={record.run_id}
              className={`grid grid-cols-[18px_1fr_auto] gap-1.5 px-2 py-1.5 border-b border-warm-50 last:border-b-0 text-xs ${
                record.run_id === selectedRunId ? "bg-warm-50" : ""
              }`}
            >
              <input
                type="checkbox"
                checked={compareRunIds.includes(record.run_id)}
                onChange={() => onToggleCompare(record.run_id)}
                aria-label={`Compare ${record.run_id}`}
              />
              <button onClick={() => onSelect(record.run_id)} className="text-left min-w-0">
                <span className="block truncate text-warm-800">{record.hypothesis || record.run_id}</span>
                <span className="text-warm-400">
                  {record.asset_class} · {record.factor_family} · {fmt(record.sharpe)}
                </span>
              </button>
              <div className="flex items-center gap-1">
                <VerdictBadge verdict={record.verdict} />
                <CriticDisagreementBadge agrees={record.critic_agrees} />
              </div>
            </div>
          ))}
          {libraryRecords.length === 0 && <div className="px-2 py-2 text-xs text-warm-400">No matching runs.</div>}
        </div>
        <button
          onClick={onOpenCompare}
          disabled={compareRunIds.length < 2}
          className="mt-2 w-full text-xs px-2 py-1.5 rounded-md bg-warm-900 text-white disabled:bg-warm-150 disabled:text-warm-500"
        >
          Compare {compareRunIds.length || ""}
        </button>
      </div>
      <LiteratureSection
        papers={papers}
        activePaperId={activePaperId}
        onOpenPaper={onOpenPaper}
        onImportPaper={onImportPaper}
        onUploadPaper={onUploadPaper}
      />
      <div className="flex-1 overflow-y-auto pb-2">
        {isLoading && <div className="px-3 py-2 text-sm text-warm-400">Loading…</div>}
        {!isLoading && runs.length === 0 && (
          <div className="px-3 py-2 text-sm text-warm-400">Start your first run above.</div>
        )}
        {Array.from(groups.entries()).map(([label, group]) => (
          <div key={label} className="mb-1 px-2">
            <div className="px-2 py-1 text-xs text-warm-400">{label}</div>
            {group.map((run) => (
              <button
                key={run.run_id}
                onClick={() => onSelect(run.run_id)}
                className={`w-full text-left px-2 py-1.5 rounded-md text-sm flex items-center gap-2 transition-colors ${
                  run.run_id === selectedRunId ? "bg-warm-100 text-warm-900" : "text-warm-700 hover:bg-warm-100/60"
                }`}
              >
                <StatusDot status={run.status} />
                <span className="truncate flex-1">{run.user_request || run.run_id}</span>
                <MonitoringStatusBadge status={run.monitoring_status} />
              </button>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
