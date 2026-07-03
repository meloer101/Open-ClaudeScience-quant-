import { useQuery } from "@tanstack/react-query";
import { getPortfolioSummary } from "../api/client";
import type { PortfolioMethodComparison } from "../types";

interface PortfolioSummaryPanelProps {
  runId: string;
}

function fmtSharpe(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  return value.toFixed(3);
}

function fmtPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "-";
  return `${(value * 100).toFixed(1)}%`;
}

// Out-of-sample decay is the whole point of showing this table: a method whose
// test Sharpe is far below its train Sharpe is
// flagged even if it happens to have the best train Sharpe of the bunch -
// that pattern (typically max_sharpe) is the expected signature of
// overfitting to noisy expected-return estimates, not something to hide.
function decayTone(row: PortfolioMethodComparison): string {
  if (row.test_sharpe === null) return "text-warm-600";
  // A negative out-of-sample Sharpe is a red flag on its own, independent of
  // the in-sample/out-of-sample ratio below - checking this first matters
  // when train_sharpe is itself negative (e.g. -16 in-sample, -18 out-of-
  // sample), where dividing test by train would otherwise flip the sign and
  // this case would fall through to the neutral train_sharpe<=0 branch even
  // though both numbers are clearly bad.
  if (row.test_sharpe < 0) return "text-danger-600";
  if (row.train_sharpe <= 0) return "text-warm-600";
  const ratio = row.test_sharpe / row.train_sharpe;
  if (ratio < 0.5) return "text-danger-600";
  // warn-700 doesn't exist in the theme scale (jumps 600 -> 800, see
  // web/src/index.css) - warn-600 is the closest defined shade for this
  // "materially decayed but not critical" tier.
  if (ratio < 0.8) return "text-warn-600";
  return "text-success-600";
}

export function PortfolioSummaryPanel({ runId }: PortfolioSummaryPanelProps) {
  const { data } = useQuery({
    queryKey: ["portfolio-summary", runId],
    queryFn: () => getPortfolioSummary(runId),
  });

  if (!data) return null;

  const methods = Object.entries(data.comparison_table);
  const selectedWeights = data.comparison_table[data.selected_method]?.weights ?? {};
  const maxWeight = Math.max(1e-6, ...Object.values(selectedWeights));

  return (
    <div className="mt-3 border border-warm-200 rounded-xl p-3">
      <div className="text-xs font-medium text-warm-500 mb-2">
        组合优化 · 选中方法 <span className="font-mono text-warm-900">{data.selected_method}</span>
        {" · "}多样化比率 {data.diversification_ratio !== null ? data.diversification_ratio.toFixed(2) : "-"}
      </div>

      <div className="mb-3">
        {Object.entries(selectedWeights).map(([factorRunId, weight]) => (
          <div key={factorRunId} className="flex items-center gap-2 text-xs mb-1">
            <span className="w-32 truncate text-warm-600 font-mono" title={factorRunId}>
              {factorRunId}
            </span>
            <div className="flex-1 h-2.5 bg-warm-50 rounded overflow-hidden">
              <div className="h-full bg-accent-500" style={{ width: `${(weight / maxWeight) * 100}%` }} />
            </div>
            <span className="w-14 text-right font-mono text-warm-800">{fmtPct(weight)}</span>
          </div>
        ))}
      </div>

      <table className="text-xs border-collapse w-full">
        <thead>
          <tr className="text-warm-400">
            <td className="pr-3 py-0.5">方法</td>
            <td className="pr-3 py-0.5 text-right">样本内 Sharpe</td>
            <td className="pr-3 py-0.5 text-right">样本外 Sharpe</td>
          </tr>
        </thead>
        <tbody>
          {methods.map(([method, row]) => (
            <tr key={method} className={method === data.selected_method ? "font-medium text-warm-900" : "text-warm-600"}>
              <td className="pr-3 py-0.5">
                {method}
                {method === data.selected_method && " ✓"}
                {method === "max_sharpe" && <span className="text-warm-400"> (对照，非推荐)</span>}
              </td>
              <td className="pr-3 py-0.5 text-right font-mono">{fmtSharpe(row.train_sharpe)}</td>
              <td className={`pr-3 py-0.5 text-right font-mono ${decayTone(row)}`}>{fmtSharpe(row.test_sharpe)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
