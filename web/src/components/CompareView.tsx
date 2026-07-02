import { useQuery } from "@tanstack/react-query";
import { compareRuns } from "../api/client";

interface CompareViewProps {
  runIds: string[];
  onClear: () => void;
}

function fmt(value: number | null | undefined): string {
  if (value === null || value === undefined) return "";
  return Number.isInteger(value) ? String(value) : value.toFixed(4);
}

export function CompareView({ runIds, onClear }: CompareViewProps) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["compare", runIds],
    queryFn: () => compareRuns(runIds),
    enabled: runIds.length >= 2,
  });

  if (runIds.length < 2) return null;

  return (
    <div className="border-b border-warm-100 bg-white px-5 py-3 shrink-0">
      <div className="flex items-center justify-between gap-3 mb-2">
        <div className="text-sm font-medium text-warm-900">Compare</div>
        <button onClick={onClear} className="text-xs text-warm-500 hover:text-warm-900">
          Clear
        </button>
      </div>
      {isLoading && <div className="text-xs text-warm-400">Loading comparison…</div>}
      {error && <div className="text-xs text-danger-600">Failed to load comparison.</div>}
      {data && (
        <div className="overflow-x-auto">
          <table className="text-xs border-collapse min-w-full">
            <thead>
              <tr>
                <th className="text-left font-medium text-warm-500 border-b border-warm-100 py-1 pr-4">metric</th>
                {data.run_ids.map((runId) => (
                  <th key={runId} className="text-left font-medium text-warm-700 border-b border-warm-100 py-1 pr-4 max-w-44">
                    <span className="block truncate" title={data.hypotheses[runId] || runId}>
                      {data.hypotheses[runId] || runId}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="py-1 pr-4 text-warm-500">verdict</td>
                {data.run_ids.map((runId) => (
                  <td key={runId} className="py-1 pr-4 text-warm-900">
                    {data.verdicts[runId] ?? ""}
                  </td>
                ))}
              </tr>
              {Object.entries(data.metrics).map(([metric, values]) => (
                <tr key={metric}>
                  <td className="py-1 pr-4 text-warm-500">{metric}</td>
                  {data.run_ids.map((runId) => (
                    <td key={runId} className="py-1 pr-4 tabular-nums text-warm-900">
                      {fmt(values[runId])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
