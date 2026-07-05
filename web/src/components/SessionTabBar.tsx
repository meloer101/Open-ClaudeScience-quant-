export interface SessionTab {
  id: string; // real run_id, or "draft" for a new unsubmitted session
  label: string;
  status: "running" | "awaiting_confirmation" | "completed" | "failed" | "cancelled" | "draft";
}

interface SessionTabBarProps {
  tabs: SessionTab[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onClose: (id: string) => void;
}

export function SessionTabBar({ tabs, activeId, onSelect, onClose }: SessionTabBarProps) {
  if (tabs.length === 0) return null;

  return (
    <div className="flex items-center gap-1 bg-warm-50 overflow-x-auto p-1.5">
      {tabs.map((tab) => (
        <div
          key={tab.id}
          onClick={() => onSelect(tab.id)}
          className={`group flex items-center gap-1.5 pl-3 pr-2 py-1.5 text-sm rounded-lg cursor-pointer max-w-56 shrink-0 transition-colors ${
            tab.id === activeId ? "bg-warm-100 text-warm-900" : "text-warm-500 hover:bg-warm-100/60"
          }`}
        >
          {(tab.status === "running" || tab.status === "awaiting_confirmation") && (
            <span className="w-1.5 h-1.5 rounded-full bg-warn-200 animate-pulse shrink-0" />
          )}
          <span className="truncate">{tab.label}</span>
          <button
            onClick={(event) => {
              event.stopPropagation();
              onClose(tab.id);
            }}
            className="text-warm-400 hover:text-warm-700 shrink-0 leading-none w-4 text-center"
            aria-label={`Close ${tab.label}`}
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
