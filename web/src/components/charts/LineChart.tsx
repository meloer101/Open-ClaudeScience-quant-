import { useMemo, useState } from "react";
import { linearScale, nearestIndex, niceTicks, padDomain } from "./scale";

export interface LineChartProps {
  values: number[];
  labels: string[];
  height?: number;
  color?: string;
  /** When set, the area between the line and this y-value is filled (e.g. 0
   * for a drawdown chart). Omit for a plain line (e.g. equity curve). */
  fillBaseline?: number;
  formatValue?: (value: number) => string;
  formatLabel?: (label: string) => string;
  /** Horizontal reference lines, e.g. a reviewer warning threshold. */
  thresholds?: Array<{ value: number; label: string; color?: string }>;
}

const WIDTH = 640;
const PADDING = { top: 12, right: 12, bottom: 20, left: 44 };

export function LineChart({
  values,
  labels,
  height = 180,
  color = "var(--color-accent-600)",
  fillBaseline,
  formatValue = (v) => v.toFixed(4),
  formatLabel = (l) => l,
  thresholds = [],
}: LineChartProps) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const plotWidth = WIDTH - PADDING.left - PADDING.right;
  const plotHeight = height - PADDING.top - PADDING.bottom;

  const { xScale, yScale, path, areaPath } = useMemo(() => {
    const domainValues = fillBaseline === undefined ? values : [...values, fillBaseline];
    const yDomain = padDomain([Math.min(...domainValues), Math.max(...domainValues)]);
    const x = linearScale([0, Math.max(1, values.length - 1)], [0, plotWidth]);
    const y = linearScale(yDomain, [plotHeight, 0]);

    const linePoints = values.map((value, index) => `${x(index)},${y(value)}`);
    const line = values.length > 0 ? `M${linePoints.join("L")}` : "";

    let area = "";
    if (fillBaseline !== undefined && values.length > 0) {
      const baseline = y(fillBaseline);
      area = `M${x(0)},${baseline} L${linePoints.join(" L")} L${x(values.length - 1)},${baseline} Z`;
    }

    return { xScale: x, yScale: y, path: line, areaPath: area };
  }, [values, fillBaseline, plotWidth, plotHeight]);

  if (values.length === 0) return null;

  const yTicks = niceTicks(yScale.domain[0], yScale.domain[1], 4);
  const hovered = hoverIndex !== null ? values[hoverIndex] : null;

  function handleMove(event: React.MouseEvent<SVGRectElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const index = nearestIndex(event.clientX - rect.left, plotWidth, values.length);
    setHoverIndex(index);
  }

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${WIDTH} ${height}`} width="100%" height={height} className="overflow-visible">
        <g transform={`translate(${PADDING.left},${PADDING.top})`}>
          {yTicks.map((tick) => (
            <g key={tick}>
              <line x1={0} x2={plotWidth} y1={yScale(tick)} y2={yScale(tick)} stroke="var(--color-warm-100)" strokeWidth={1} />
              <text x={-6} y={yScale(tick)} textAnchor="end" dominantBaseline="middle" fontSize={9} fill="var(--color-warm-400)">
                {formatValue(tick)}
              </text>
            </g>
          ))}
          {thresholds.map((threshold, index) => (
            <g key={`${threshold.label}-${index}-${threshold.value}`}>
              <line
                x1={0}
                x2={plotWidth}
                y1={yScale(threshold.value)}
                y2={yScale(threshold.value)}
                stroke={threshold.color ?? "var(--color-warn-200)"}
                strokeWidth={1}
                strokeDasharray="4 3"
              />
              <text x={plotWidth} y={yScale(threshold.value) - 3} textAnchor="end" fontSize={9} fill={threshold.color ?? "var(--color-warn-600)"}>
                {threshold.label}
              </text>
            </g>
          ))}
          {areaPath && <path d={areaPath} fill={color} fillOpacity={0.15} stroke="none" />}
          <path d={path} fill="none" stroke={color} strokeWidth={1.6} />
          {hoverIndex !== null && (
            <line x1={xScale(hoverIndex)} x2={xScale(hoverIndex)} y1={0} y2={plotHeight} stroke="var(--color-warm-300)" strokeWidth={1} />
          )}
          <rect
            x={0}
            y={0}
            width={plotWidth}
            height={plotHeight}
            fill="transparent"
            onMouseMove={handleMove}
            onMouseLeave={() => setHoverIndex(null)}
          />
        </g>
      </svg>
      {hoverIndex !== null && hovered !== null && (
        <div className="absolute top-1 right-1 bg-white border border-warm-150 rounded-md px-2 py-1 text-xs text-warm-800 shadow-sm pointer-events-none">
          <div className="text-warm-400">{formatLabel(labels[hoverIndex] ?? "")}</div>
          <div className="tabular-nums font-medium">{formatValue(hovered)}</div>
        </div>
      )}
    </div>
  );
}
