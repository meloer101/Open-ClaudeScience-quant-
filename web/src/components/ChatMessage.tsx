import Markdown from "react-markdown";
import type { RunDetail, RunEvent } from "../types";
import { WarningBanner } from "./WarningBanner";
import { ArtifactGallery } from "./ArtifactGallery";
import { LiveProgress } from "./LiveProgress";

interface ChatMessageProps {
  run: RunDetail;
  liveEvents: RunEvent[];
  selectedFilename: string | null;
  onSelectArtifact: (filename: string) => void;
}

function MetricsTable({ metrics }: { metrics: Record<string, number> }) {
  const entries = Object.entries(metrics);
  if (entries.length === 0) return null;
  return (
    <table className="text-sm border-collapse my-2">
      <tbody>
        {entries.map(([key, value]) => (
          <tr key={key}>
            <td className="pr-4 py-0.5 text-slate-500">{key}</td>
            <td className="py-0.5 font-mono text-slate-800">
              {typeof value === "number" ? value.toLocaleString(undefined, { maximumFractionDigits: 4 }) : value}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function ChatMessage({ run, liveEvents, selectedFilename, onSelectArtifact }: ChatMessageProps) {
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <div className="max-w-2xl bg-blue-600 text-white rounded-2xl rounded-br-sm px-4 py-2.5 text-sm">
          {run.user_request}
        </div>
      </div>

      <div className="max-w-3xl">
        {run.status === "running" && <LiveProgress events={liveEvents} />}
        {run.status === "failed" && (
          <div className="border-2 border-red-400 bg-red-50 rounded-lg p-3 text-sm text-red-800">
            <div className="font-bold mb-1">运行失败</div>
            <pre className="whitespace-pre-wrap text-xs">{run.error || "Unknown error"}</pre>
          </div>
        )}
        {run.status === "completed" && (
          <>
            <WarningBanner warnings={run.warnings} />
            <MetricsTable metrics={run.metrics} />
            <div className="prose prose-sm max-w-none">
              <Markdown>{run.summary}</Markdown>
            </div>
            <ArtifactGallery
              runId={run.run_id}
              artifacts={run.artifacts}
              selectedFilename={selectedFilename}
              onSelect={onSelectArtifact}
            />
          </>
        )}
      </div>
    </div>
  );
}
