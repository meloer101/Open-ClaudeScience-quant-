export interface SessionTab {
  id: string; // real run_id, or "draft" for a new unsubmitted session
  label: string;
  status: "running" | "completed" | "failed" | "draft";
}

interface SessionTabBarProps {
  tabs: SessionTab[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onClose: (id: string) => void;
}

const STATUS_DOT: Record<SessionTab["status"], string> = {
  running: "bg-amber-400 animate-pulse",
  completed: "bg-emerald-500",
  failed: "bg-red-500",
  draft: "bg-slate-300",
};

export function SessionTabBar({ tabs, activeId, onSelect, onClose }: SessionTabBarProps) {
  if (tabs.length === 0) return null;

  return (
    <div className="flex items-stretch border-b border-slate-200 bg-slate-50 overflow-x-auto">
      {tabs.map((tab) => (
        <div
          key={tab.id}
          onClick={() => onSelect(tab.id)}
          className={`group flex items-center gap-2 px-3 py-2 text-sm border-r border-slate-200 cursor-pointer max-w-56 shrink-0 ${
            tab.id === activeId ? "bg-white font-medium text-slate-800" : "text-slate-500 hover:bg-slate-100"
          }`}
        >
          <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${STATUS_DOT[tab.status]}`} />
          <span className="truncate">{tab.label}</span>
          <button
            onClick={(event) => {
              event.stopPropagation();
              onClose(tab.id);
            }}
            className="opacity-0 group-hover:opacity-100 text-slate-400 hover:text-slate-700 shrink-0"
            aria-label={`Close ${tab.label}`}
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
