import { useQuery } from "@tanstack/react-query";
import { getBacktestResult, getReviewReport } from "../api/client";
import { LineChart } from "./charts/LineChart";
import { BarChart, type BarDatum } from "./charts/BarChart";
import { HeatmapGrid } from "./charts/HeatmapGrid";
import { StatCard } from "./charts/StatCard";
import { findingByCheck, formatTimestampLabel, monthlyGroupReturnHeatmap } from "./charts/deriveChartData";

interface ChartsPanelProps {
  runId: string;
}

function Section({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div className="mb-6">
      <div className="mb-1.5">
        <div className="text-xs font-medium text-warm-700">{title}</div>
        {subtitle && <div className="text-[10px] text-warm-400">{subtitle}</div>}
      </div>
      {children}
    </div>
  );
}

function pct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

// Reviewer thresholds duplicated here for the reference lines only (rendering
// annotations, not judgments) - the actual verdict is always computed by
// quantbench/review/report.py and never recomputed on the frontend. See
// REGIME_CONCENTRATION_THRESHOLD in that file.
const REGIME_CONCENTRATION_THRESHOLD = 0.7;

export function ChartsPanel({ runId }: ChartsPanelProps) {
  const { data: backtest, isLoading: backtestLoading } = useQuery({
    queryKey: ["backtest-result", runId],
    queryFn: () => getBacktestResult(runId),
  });
  const { data: review, isLoading: reviewLoading } = useQuery({
    queryKey: ["review-report", runId],
    queryFn: () => getReviewReport(runId),
  });

  if (backtestLoading || reviewLoading) {
    return <div className="p-4 text-sm text-warm-400">Loading charts…</div>;
  }
  if (!backtest) {
    return <div className="p-4 text-sm text-warm-400">No backtest data available for this run.</div>;
  }

  const timestamps = backtest.series.timestamp;
  const labels = timestamps.map(formatTimestampLabel);
  const findings = review?.findings ?? [];
  const isCrossSectional = Boolean(backtest.group_returns);

  const costFinding = findingByCheck(findings, "cost_sensitivity");
  const parameterFinding = findingByCheck(findings, "parameter_stability");
  const regimeFinding = findingByCheck(findings, "regime");
  const betaFinding = findingByCheck(findings, "beta_exposure");
  const tailFinding = findingByCheck(findings, "tail_dependence");
  const symbolFinding = findingByCheck(findings, "symbol_concentration");

  const costData: BarDatum[] | null = costFinding
    ? Object.entries(costFinding.detail.sharpe_by_multiplier as Record<string, number>)
        .sort(([a], [b]) => Number(a) - Number(b))
        .map(([multiplier, sharpe]) => ({ label: `${multiplier}x`, value: sharpe }))
    : null;

  const parameterData: BarDatum[] | null = parameterFinding
    ? (["−20%", "base", "+20%"] as const)
        .map((label): BarDatum | null => {
          const key = label === "−20%" ? "-20%" : label;
          const raw = (parameterFinding.detail.sharpe_by_perturbation as Record<string, number>)[key];
          return raw === undefined ? null : { label, value: raw };
        })
        .filter((datum): datum is BarDatum => datum !== null)
    : null;

  const regimeData: BarDatum[] | null = regimeFinding
    ? Object.entries(regimeFinding.detail.yearly_contribution as Record<string, number>)
        .sort(([a], [b]) => Number(a) - Number(b))
        .map(([year, contribution]) => ({ label: year, value: contribution }))
    : null;

  const symbolData: BarDatum[] | null = symbolFinding
    ? Object.entries(symbolFinding.detail.top_symbols as Record<string, number>)
        .sort(([, a], [, b]) => Math.abs(b) - Math.abs(a))
        .map(([symbol, contribution]) => ({ label: symbol, value: contribution }))
    : null;

  const decileData: BarDatum[] | null = backtest.group_returns
    ? Object.entries(backtest.group_returns)
        .sort(([a], [b]) => Number(a) - Number(b))
        .map(([group, series]) => {
          const clean = series.filter((v) => !Number.isNaN(v));
          const mean = clean.length > 0 ? clean.reduce((sum, v) => sum + v, 0) / clean.length : 0;
          return { label: `G${group}`, value: mean };
        })
    : null;

  const heatmap = backtest.group_returns ? monthlyGroupReturnHeatmap(timestamps, backtest.group_returns) : null;

  return (
    <div className="p-4">
      <Section title="Equity Curve">
        <LineChart values={backtest.series.equity_curve} labels={labels} formatValue={(v) => v.toFixed(3)} />
      </Section>

      <Section title="Drawdown">
        <LineChart
          values={backtest.series.drawdown}
          labels={labels}
          fillBaseline={0}
          color="var(--color-danger-400)"
          formatValue={pct}
        />
      </Section>

      {backtest.series.turnover && (
        <Section title="Turnover" subtitle="Per-period position turnover">
          <LineChart values={backtest.series.turnover} labels={labels} color="var(--color-warm-600)" formatValue={(v) => v.toFixed(2)} />
        </Section>
      )}

      {isCrossSectional && backtest.series.ic && (
        <Section title="Rank IC Over Time">
          <LineChart values={backtest.series.ic} labels={labels} color="#7c2d12" formatValue={(v) => v.toFixed(3)} />
        </Section>
      )}

      {isCrossSectional && decileData && (
        <Section title="Decile Return Bar" subtitle="Average forward return by factor group">
          <BarChart data={decileData} formatValue={pct} />
        </Section>
      )}

      {isCrossSectional && heatmap && heatmap.columnLabels.length > 0 && (
        <Section
          title="Decile Return Heatmap"
          subtitle="Monthly average return by group - not a per-symbol IC heatmap (QuantBench doesn't persist per-symbol IC yet, see PHASE4.md)"
        >
          <HeatmapGrid rowLabels={heatmap.rowLabels} columnLabels={heatmap.columnLabels} values={heatmap.values} formatValue={pct} />
        </Section>
      )}

      {costData && (
        <Section title="Cost Sensitivity" subtitle="Sharpe at 1x / 1.5x / 2x assumed trading cost">
          <BarChart data={costData} formatValue={(v) => v.toFixed(2)} />
        </Section>
      )}

      {parameterData && (
        <Section title="Parameter Perturbation" subtitle="Sharpe under ±20% numeric-literal perturbation (not a grid search)">
          <BarChart data={parameterData} formatValue={(v) => v.toFixed(2)} />
        </Section>
      )}

      {regimeData && (
        <Section title="Regime Decomposition" subtitle="Return contribution by calendar year">
          <BarChart
            data={regimeData}
            formatValue={pct}
            thresholds={[
              { value: REGIME_CONCENTRATION_THRESHOLD, label: `+${pct(REGIME_CONCENTRATION_THRESHOLD)}`, color: "var(--color-warn-200)" },
              { value: -REGIME_CONCENTRATION_THRESHOLD, label: `-${pct(REGIME_CONCENTRATION_THRESHOLD)}`, color: "var(--color-warn-200)" },
            ]}
          />
        </Section>
      )}

      {isCrossSectional && symbolData && (
        <Section title="Symbol Concentration" subtitle="Top contributing symbols to the long-short leg">
          <BarChart data={symbolData} formatValue={pct} />
        </Section>
      )}

      {(betaFinding || tailFinding) && (
        <Section title="Other Reviewer Stats">
          <div className="flex flex-wrap gap-2">
            {betaFinding && (
              <>
                <StatCard label="Beta" value={(betaFinding.detail.beta as number).toFixed(2)} />
                <StatCard label="R²" value={(betaFinding.detail.r_squared as number).toFixed(2)} />
                <StatCard label="Observations" value={String(betaFinding.detail.observations)} />
              </>
            )}
            {tailFinding && (
              <StatCard
                label="Best-days return share"
                value={pct(tailFinding.detail.best_days_positive_return_share as number)}
                sublabel="Top 5% of days"
              />
            )}
          </div>
        </Section>
      )}
    </div>
  );
}
