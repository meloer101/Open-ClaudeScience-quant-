export interface StatCardProps {
  label: string;
  value: string;
  sublabel?: string;
}

/**
 * A single scalar stat (e.g. beta exposure), deliberately not a chart.
 * VISION.md's "Risk Attribution" entry implies a multi-factor breakdown
 * QuantBench has no data source for yet; rendering the one real number
 * (beta vs. a single benchmark) as a plain stat avoids
 * dressing it up as something more precise than it is.
 */
export function StatCard({ label, value, sublabel }: StatCardProps) {
  return (
    <div className="rounded-lg border border-warm-100 bg-warm-25 px-3 py-2 min-w-28">
      <div className="text-[10px] text-warm-400 uppercase tracking-wide">{label}</div>
      <div className="text-sm font-medium text-warm-900 tabular-nums">{value}</div>
      {sublabel && <div className="text-[10px] text-warm-400">{sublabel}</div>}
    </div>
  );
}
