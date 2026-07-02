import type { RunSummary } from "../types";

interface SidebarProps {
  runs: RunSummary[];
  selectedRunId: string | null;
  onSelect: (runId: string) => void;
  onNew: () => void;
  isLoading: boolean;
  width: number;
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

export function Sidebar({ runs, selectedRunId, onSelect, onNew, isLoading, width }: SidebarProps) {
  const groups = new Map<string, RunSummary[]>();
  for (const run of runs) {
    const label = dateGroupLabel(run.created_at);
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label)!.push(run);
  }

  return (
    <div className="shrink-0 bg-warm-25 h-full flex flex-col overflow-hidden" style={{ width }}>
      <div className="px-3 pt-4 pb-3">
        <div className="font-medium text-warm-900 mb-3 px-1">QuantBench</div>
        <button
          onClick={onNew}
          className="w-full text-left text-sm px-2.5 py-1.5 rounded-md text-warm-700 hover:bg-warm-100 transition-colors flex items-center gap-1.5"
        >
          <span className="text-warm-400">+</span>
          New
        </button>
      </div>
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
              </button>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
