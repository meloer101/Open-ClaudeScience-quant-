import Markdown from "react-markdown";
import type { RunDetail } from "../types";
import { WarningBanner } from "./WarningBanner";
import { ArtifactGallery } from "./ArtifactGallery";

interface ChatMessageProps {
  run: RunDetail;
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

export function ChatMessage({ run, selectedFilename, onSelectArtifact }: ChatMessageProps) {
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <div className="max-w-2xl bg-blue-600 text-white rounded-2xl rounded-br-sm px-4 py-2.5 text-sm">
          {run.user_request}
        </div>
      </div>

      <div className="max-w-3xl">
        {run.status === "running" && (
          <div className="text-sm text-slate-500 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
            正在运行，请稍候…
          </div>
        )}
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
