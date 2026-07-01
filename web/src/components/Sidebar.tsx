import type { RunSummary } from "../types";

interface SidebarProps {
  runs: RunSummary[];
  selectedRunId: string | null;
  onSelect: (runId: string) => void;
  onNew: () => void;
  isLoading: boolean;
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

function statusDot(status: RunSummary["status"]) {
  const color =
    status === "completed" ? "bg-emerald-500" : status === "failed" ? "bg-red-500" : "bg-amber-400 animate-pulse";
  return <span className={`inline-block w-2 h-2 rounded-full ${color}`} aria-label={status} />;
}

export function Sidebar({ runs, selectedRunId, onSelect, onNew, isLoading }: SidebarProps) {
  const groups = new Map<string, RunSummary[]>();
  for (const run of runs) {
    const label = dateGroupLabel(run.created_at);
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label)!.push(run);
  }

  return (
    <div className="w-64 shrink-0 border-r border-slate-200 bg-white h-full flex flex-col">
      <div className="p-3 border-b border-slate-200">
        <div className="font-semibold text-slate-800 mb-2">QuantBench</div>
        <button
          onClick={onNew}
          className="w-full text-left text-sm px-3 py-1.5 rounded-md border border-slate-300 hover:bg-slate-50 text-slate-700"
        >
          + New
        </button>
      </div>
      <div className="flex-1 overflow-y-auto py-2">
        {isLoading && <div className="px-3 py-2 text-sm text-slate-400">Loading…</div>}
        {!isLoading && runs.length === 0 && (
          <div className="px-3 py-2 text-sm text-slate-400">还没有任何 run，点上面 + New 开始</div>
        )}
        {Array.from(groups.entries()).map(([label, group]) => (
          <div key={label} className="mb-2">
            <div className="px-3 py-1 text-xs font-semibold text-slate-400 uppercase tracking-wide">{label}</div>
            {group.map((run) => (
              <button
                key={run.run_id}
                onClick={() => onSelect(run.run_id)}
                className={`w-full text-left px-3 py-2 text-sm flex items-start gap-2 hover:bg-slate-50 ${
                  run.run_id === selectedRunId ? "bg-slate-100" : ""
                }`}
              >
                <span className="mt-1.5">{statusDot(run.status)}</span>
                <span className="truncate flex-1 text-slate-700">{run.user_request || run.run_id}</span>
              </button>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
