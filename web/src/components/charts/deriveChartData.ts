// Pure data-shaping helpers for ChartsPanel. Kept separate from the
// component so the aggregation logic (the one non-trivial computation in
// this Phase's frontend work) can be reasoned about independently of
// rendering - it takes already-serialized backend JSON and reshapes it, it
// never invents numbers.

import type { ReviewFindingPayload } from "../../types";

export function findingByCheck(findings: ReviewFindingPayload[], check: string): ReviewFindingPayload | null {
  return findings.find((finding) => finding.check === check && finding.severity !== "info") ?? null;
}

/**
 * Buckets a decile/group return series into monthly averages per group, for
 * the HeatmapGrid in ChartsPanel. This is an honest substitute for VISION's
 * per-symbol "Factor IC Heatmap" - QuantBench has no persisted per-symbol IC
 * to draw from, but it does have per-period decile
 * returns (group_returns), so this reshapes *that* into a readable
 * time-x-group grid instead of pretending to be the symbol-level chart.
 */
export function monthlyGroupReturnHeatmap(
  timestamps: string[],
  groupReturns: Record<string, number[]>,
): { rowLabels: string[]; columnLabels: string[]; values: (number | null)[][] } {
  const groupKeys = Object.keys(groupReturns).sort((a, b) => Number(a) - Number(b));
  const months = Array.from(
    new Set(timestamps.map((ts) => ts.slice(0, 7))), // "YYYY-MM"
  ).sort();

  const sums = new Map<string, number>(); // `${group}|${month}` -> sum
  const counts = new Map<string, number>();

  for (const group of groupKeys) {
    const series = groupReturns[group] ?? [];
    for (let i = 0; i < timestamps.length; i += 1) {
      const value = series[i];
      if (value === undefined || value === null || Number.isNaN(value)) continue;
      const month = timestamps[i].slice(0, 7);
      const key = `${group}|${month}`;
      sums.set(key, (sums.get(key) ?? 0) + value);
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
  }

  const values = groupKeys.map((group) =>
    months.map((month) => {
      const key = `${group}|${month}`;
      const count = counts.get(key);
      if (!count) return null;
      return (sums.get(key) ?? 0) / count;
    }),
  );

  return { rowLabels: groupKeys.map((g) => `G${g}`), columnLabels: months, values };
}

export function formatTimestampLabel(timestamp: string): string {
  return timestamp.slice(0, 10);
}
