import { useQuery } from "@tanstack/react-query";
import { getLineage } from "../api/client";

interface RunLineageProps {
  runId: string;
}

function fmt(value: number | null | undefined): string {
  if (value === null || value === undefined) return "";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(4)}`;
}

export function RunLineage({ runId }: RunLineageProps) {
  const { data, isLoading } = useQuery({
    queryKey: ["lineage", runId],
    queryFn: () => getLineage(runId),
  });

  return (
    <div className="mt-4 border-t border-warm-100 pt-3">
      <div className="text-xs font-medium text-warm-500 mb-2">Lineage</div>
      {isLoading && <div className="text-xs text-warm-400">Loading lineage…</div>}
      {data && (
        <>
          <div className="flex flex-wrap items-center gap-1.5 text-xs text-warm-700 mb-2">
            {data.chain.map((node, index) => (
              <span key={node.run_id} className="flex items-center gap-1.5">
                {index > 0 && <span className="text-warm-300">→</span>}
                <span className={node.run_id === runId ? "font-medium text-warm-900" : ""}>{node.run_id}</span>
              </span>
            ))}
          </div>
          {data.edges.map((edge) => (
            <div key={`${edge.parent_run_id}:${edge.child_run_id}`} className="text-xs text-warm-600 mb-2">
              <div>
                {edge.parent_run_id} → {edge.child_run_id} · sharpe {fmt(edge.metric_delta.sharpe)}
              </div>
              {edge.signal_diff && (
                <pre className="mt-1 max-h-28 overflow-auto bg-warm-50 border border-warm-100 rounded-md p-2 text-[11px] text-warm-800 whitespace-pre-wrap">
                  {edge.signal_diff}
                </pre>
              )}
            </div>
          ))}
        </>
      )}
    </div>
  );
}
