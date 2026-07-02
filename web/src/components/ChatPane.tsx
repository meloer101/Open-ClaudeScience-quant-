import type { RunDetail, RunEvent } from "../types";
import { ChatMessage } from "./ChatMessage";
import { ChatInput } from "./ChatInput";
import { CompareView } from "./CompareView";
import { ForkRunForm } from "./ForkRunForm";
import { RunLineage } from "./RunLineage";

interface ChatPaneProps {
  run: RunDetail | null;
  isLoading: boolean;
  isDraft: boolean;
  liveEvents: RunEvent[];
  selectedFilename: string | null;
  onSelectArtifact: (filename: string) => void;
  onSubmit: (request: string) => Promise<void>;
  compareRunIds: string[];
  onClearCompare: () => void;
  onForked: (runId: string) => void;
}

export function ChatPane({
  run,
  isLoading,
  isDraft,
  liveEvents,
  selectedFilename,
  onSelectArtifact,
  onSubmit,
  compareRunIds,
  onClearCompare,
  onForked,
}: ChatPaneProps) {
  return (
    <div className="flex-1 flex flex-col h-full min-w-0">
      <CompareView runIds={compareRunIds} onClear={onClearCompare} />
      <div className="flex-1 overflow-y-auto p-6">
        {isDraft && (
          <div className="h-full flex items-center justify-center text-warm-400 text-sm">
            提出一个量化研究问题开始，比如「测试 RSI(14) 反转因子在 AAPL 上的表现」
          </div>
        )}
        {!isDraft && !run && isLoading && <div className="text-sm text-warm-400">Loading…</div>}
        {!isDraft && !run && !isLoading && (
          <div className="h-full flex items-center justify-center text-warm-400 text-sm">选一个会话开始</div>
        )}
        {run && (
          <>
            <ChatMessage
              run={run}
              liveEvents={liveEvents}
              selectedFilename={selectedFilename}
              onSelectArtifact={onSelectArtifact}
            />
            <RunLineage runId={run.run_id} />
            {run.status === "completed" && <ForkRunForm runId={run.run_id} onForked={onForked} />}
          </>
        )}
      </div>
      <ChatInput onSubmit={onSubmit} />
    </div>
  );
}
