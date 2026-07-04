import type { ResearchSession, RunDetail, RunEvent } from "../types";
import { ChatMessage } from "./ChatMessage";
import { ChatInput } from "./ChatInput";
import { CompareView } from "./CompareView";
import { ForkRunForm } from "./ForkRunForm";
import { RunLineage } from "./RunLineage";

interface ChatPaneProps {
  run: RunDetail | null;
  session: ResearchSession | null;
  sessionRuns: RunDetail[];
  isLoading: boolean;
  isDraft: boolean;
  liveEvents: RunEvent[];
  liveRunId: string | null;
  selectedFilename: string | null;
  onSelectArtifact: (runId: string, filename: string) => void;
  onOpenCharts?: (runId: string) => void;
  isChartsSelected?: boolean;
  isChartsSelectedForRun?: (runId: string) => boolean;
  onSubmit: (request: string) => Promise<void>;
  isRunning?: boolean;
  onStop?: () => void;
  onConfirmStaging: (overrides: Record<string, unknown>) => Promise<void>;
  compareRunIds: string[];
  onClearCompare: () => void;
  onForked: (runId: string) => void;
}

export function ChatPane({
  run,
  session,
  sessionRuns,
  isLoading,
  isDraft,
  liveEvents,
  liveRunId,
  selectedFilename,
  onSelectArtifact,
  onOpenCharts,
  isChartsSelected,
  isChartsSelectedForRun,
  onSubmit,
  isRunning,
  onStop,
  onConfirmStaging,
  compareRunIds,
  onClearCompare,
  onForked,
}: ChatPaneProps) {
  const runsById = new Map(sessionRuns.map((item) => [item.run_id, item]));

  return (
    <div className="flex-1 flex flex-col h-full min-w-0">
      <CompareView runIds={compareRunIds} onClear={onClearCompare} />
      <div className="flex-1 overflow-y-auto p-6">
        {isDraft && (
          <div className="h-full flex items-center justify-center text-warm-400 text-sm">
            提出一个量化研究问题开始，比如「测试 RSI(14) 反转因子在 AAPL 上的表现」
          </div>
        )}
        {!isDraft && !run && !session && isLoading && <div className="text-sm text-warm-400">Loading…</div>}
        {!isDraft && !run && !session && !isLoading && (
          <div className="h-full flex items-center justify-center text-warm-400 text-sm">选一个会话开始</div>
        )}
        {session && (
          <div className="space-y-6">
            {session.turns.map((turn) => {
              const turnRun = turn.run_id ? runsById.get(turn.run_id) : null;
              return (
                <div key={turn.turn_index} className="space-y-3">
                  {turnRun ? (
                    <>
                      <ChatMessage
                        run={turnRun}
                        liveEvents={turnRun.run_id === liveRunId ? liveEvents : []}
                        selectedFilename={selectedFilename}
                        onSelectArtifact={(filename) => onSelectArtifact(turnRun.run_id, filename)}
                        onOpenCharts={onOpenCharts ? () => onOpenCharts(turnRun.run_id) : undefined}
                        isChartsSelected={isChartsSelectedForRun?.(turnRun.run_id) ?? false}
                        onConfirmStaging={onConfirmStaging}
                      />
                      {turnRun.status === "completed" && <RunLineage runId={turnRun.run_id} />}
                    </>
                  ) : (
                    <div className="flex justify-end">
                      <div className="max-w-2xl bg-warm-900 text-white rounded-2xl rounded-br-sm px-4 py-2.5 text-sm">
                        {turn.user_message}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
        {run && (
          <>
            <ChatMessage
              run={run}
              liveEvents={liveEvents}
              selectedFilename={selectedFilename}
              onSelectArtifact={(filename) => onSelectArtifact(run.run_id, filename)}
              onOpenCharts={onOpenCharts ? () => onOpenCharts(run.run_id) : undefined}
              isChartsSelected={isChartsSelected}
              onConfirmStaging={onConfirmStaging}
            />
            <RunLineage runId={run.run_id} />
            {run.status === "completed" && <ForkRunForm runId={run.run_id} onForked={onForked} />}
          </>
        )}
      </div>
      <ChatInput onSubmit={onSubmit} isRunning={isRunning} onStop={onStop} />
    </div>
  );
}
