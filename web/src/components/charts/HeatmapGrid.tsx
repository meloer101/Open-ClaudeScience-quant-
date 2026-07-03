export interface HeatmapGridProps {
  rowLabels: string[];
  columnLabels: string[];
  /** values[row][column] */
  values: (number | null)[][];
  formatValue?: (value: number) => string;
}

/**
 * A plain diverging-color grid, not a specific "IC heatmap" - QuantBench does
 * not persist per-symbol IC, so this renders whatever grid data it's given
 * (e.g. decile-return-by-month) rather than pretending to be the symbol-level
 * heatmap VISION.md's chart list describes.
 */
export function HeatmapGrid({ rowLabels, columnLabels, values, formatValue = (v) => v.toFixed(3) }: HeatmapGridProps) {
  const flat = values.flat().filter((v): v is number => v !== null);
  if (flat.length === 0) return null;
  const maxAbs = Math.max(...flat.map((v) => Math.abs(v)), 1e-9);

  function cellColor(value: number | null): string {
    if (value === null) return "var(--color-warm-50)";
    const intensity = Math.min(1, Math.abs(value) / maxAbs);
    return value >= 0
      ? `color-mix(in srgb, var(--color-accent-600) ${Math.round(intensity * 80)}%, white)`
      : `color-mix(in srgb, var(--color-danger-400) ${Math.round(intensity * 80)}%, white)`;
  }

  return (
    <div className="overflow-x-auto">
      <table className="text-[10px] border-collapse">
        <thead>
          <tr>
            <th className="w-16" />
            {columnLabels.map((label) => (
              <th key={label} className="px-1 py-0.5 font-normal text-warm-500 whitespace-nowrap">
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rowLabels.map((rowLabel, rowIndex) => (
            <tr key={rowLabel}>
              <td className="pr-2 py-0.5 text-warm-500 whitespace-nowrap">{rowLabel}</td>
              {columnLabels.map((_, colIndex) => {
                const value = values[rowIndex]?.[colIndex] ?? null;
                return (
                  <td
                    key={colIndex}
                    title={value === null ? "no data" : formatValue(value)}
                    className="w-10 h-6 text-center align-middle border border-white"
                    style={{ backgroundColor: cellColor(value) }}
                  >
                    <span className="text-warm-900">{value === null ? "" : formatValue(value)}</span>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
