import type { RunEvent } from "../types";

const TOOL_LABEL: Record<string, string> = {
  fetch_ohlcv: "拉取行情数据",
  run_signal_backtest: "跑单标的回测",
  build_universe: "构建 universe",
  run_cross_sectional_backtest: "跑截面回测",
  screen_factors: "批量筛选因子",
};

function describeArgs(args: Record<string, unknown>): string {
  const parts = Object.entries(args)
    .filter(([key]) => key !== "code")
    .map(([key, value]) => `${key}=${String(value)}`);
  return parts.join(", ");
}

function StepLine({ event, pending }: { event: RunEvent; pending: boolean }) {
  if (event.type === "tool_start") {
    const label = TOOL_LABEL[event.tool] ?? event.tool;
    return (
      <div className="flex items-center gap-2 text-sm text-warm-700">
        <span
          className={`w-1.5 h-1.5 rounded-full shrink-0 ${pending ? "bg-warn-200 animate-pulse" : "bg-success-400"}`}
        />
        <span className="font-medium">{label}</span>
        <span className="text-warm-400 text-xs truncate">{describeArgs(event.args)}</span>
      </div>
    );
  }
  if (event.type === "tool_end") {
    const result = event.result as Record<string, unknown>;
    const hasError = result && typeof result === "object" && "error" in result;
    return (
      <div className={`text-xs pl-3.5 ${hasError ? "text-danger-600" : "text-warm-400"}`}>
        {hasError ? String(result.error) : "完成"}
      </div>
    );
  }
  return null;
}

interface LiveProgressProps {
  events: RunEvent[];
}

export function LiveProgress({ events }: LiveProgressProps) {
  if (events.length === 0) {
    return (
      <div className="text-sm text-warm-500 flex items-center gap-2">
        <span className="w-1.5 h-1.5 rounded-full bg-warn-200 animate-pulse" />
        正在启动…
      </div>
    );
  }

  // A tool_start is "pending" until its matching tool_end shows up later in
  // the list.
  const startIndexByTool = new Map<number, boolean>();
  events.forEach((event, index) => {
    if (event.type === "tool_start") {
      const hasEnd = events
        .slice(index + 1)
        .some((later) => later.type === "tool_end" && later.tool === event.tool);
      startIndexByTool.set(index, !hasEnd);
    }
  });

  return (
    <div className="space-y-1.5 border border-warm-100 rounded-xl p-3 bg-warm-25">
      {events.map((event, index) =>
        event.type === "tool_start" || event.type === "tool_end" ? (
          <StepLine key={index} event={event} pending={startIndexByTool.get(index) ?? false} />
        ) : null,
      )}
    </div>
  );
}
