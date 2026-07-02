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
  onOpenCharts?: () => void;
  isChartsSelected?: boolean;
}

function MetricsTable({ metrics }: { metrics: Record<string, number> }) {
  const entries = Object.entries(metrics);
  if (entries.length === 0) return null;
  return (
    <table className="text-sm border-collapse my-2">
      <tbody>
        {entries.map(([key, value]) => (
          <tr key={key}>
            <td className="pr-4 py-0.5 text-warm-500">{key}</td>
            <td className="py-0.5 font-mono text-warm-800">
              {typeof value === "number" ? value.toLocaleString(undefined, { maximumFractionDigits: 4 }) : value}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// Historical cross-sectional runs wrote their result under this name before
// it was unified with the single-symbol path's "backtest_result.json" (see
// run_reader.read_backtest_result on the backend, which resolves either).
// The gate for showing the Interactive Charts entry point must recognize
// both names too, or it silently hides the entry point for exactly the runs
// the backend fallback exists to support.
const LEGACY_CROSS_SECTIONAL_BACKTEST_RESULT_FILENAME = "cross_sectional_backtest_result.json";

export function ChatMessage({ run, liveEvents, selectedFilename, onSelectArtifact, onOpenCharts, isChartsSelected }: ChatMessageProps) {
  const hasBacktestResult = run.artifacts.some(
    (artifact) =>
      artifact.filename === "backtest_result.json" || artifact.filename === LEGACY_CROSS_SECTIONAL_BACKTEST_RESULT_FILENAME,
  );
  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <div className="max-w-2xl bg-warm-900 text-white rounded-2xl rounded-br-sm px-4 py-2.5 text-sm">
          {run.user_request}
        </div>
      </div>

      <div className="max-w-3xl">
        {run.status === "running" && <LiveProgress events={liveEvents} />}
        {run.status === "failed" && (
          <div className="border border-danger-200 bg-danger-50 rounded-xl p-3 text-sm text-danger-900">
            <div className="font-medium mb-1">运行失败</div>
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
              onOpenCharts={hasBacktestResult ? onOpenCharts : undefined}
              isChartsSelected={isChartsSelected}
            />
          </>
        )}
      </div>
    </div>
  );
}
