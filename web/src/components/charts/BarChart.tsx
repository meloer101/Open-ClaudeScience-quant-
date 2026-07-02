import { useMemo, useState } from "react";
import { linearScale, niceTicks, padDomain } from "./scale";

export interface BarDatum {
  label: string;
  value: number;
}

export interface BarChartProps {
  data: BarDatum[];
  height?: number;
  positiveColor?: string;
  negativeColor?: string;
  formatValue?: (value: number) => string;
  thresholds?: Array<{ value: number; label: string; color?: string }>;
}

const WIDTH = 640;
const PADDING = { top: 12, right: 12, bottom: 28, left: 44 };

export function BarChart({
  data,
  height = 180,
  positiveColor = "var(--color-accent-600)",
  negativeColor = "var(--color-danger-400)",
  formatValue = (v) => v.toFixed(4),
  thresholds = [],
}: BarChartProps) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  const plotWidth = WIDTH - PADDING.left - PADDING.right;
  const plotHeight = height - PADDING.top - PADDING.bottom;

  const { yScale, barWidth } = useMemo(() => {
    const values = data.map((d) => d.value);
    const domain = padDomain([Math.min(0, ...values), Math.max(0, ...values)]);
    return {
      yScale: linearScale(domain, [plotHeight, 0]),
      barWidth: data.length > 0 ? (plotWidth / data.length) * 0.6 : 0,
    };
  }, [data, plotWidth, plotHeight]);

  if (data.length === 0) return null;

  const yTicks = niceTicks(yScale.domain[0], yScale.domain[1], 4);
  const zeroY = yScale(0);
  const slot = plotWidth / data.length;

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
          {data.map((datum, index) => {
            const barY = Math.min(yScale(datum.value), zeroY);
            const barHeight = Math.abs(yScale(datum.value) - zeroY);
            const x = slot * index + (slot - barWidth) / 2;
            return (
              <g key={datum.label} onMouseEnter={() => setHoverIndex(index)} onMouseLeave={() => setHoverIndex(null)}>
                <rect
                  x={x}
                  y={barY}
                  width={barWidth}
                  height={Math.max(barHeight, 1)}
                  fill={datum.value >= 0 ? positiveColor : negativeColor}
                  fillOpacity={hoverIndex === index ? 1 : 0.85}
                />
                <text x={slot * index + slot / 2} y={plotHeight + 14} textAnchor="middle" fontSize={9} fill="var(--color-warm-500)">
                  {datum.label}
                </text>
              </g>
            );
          })}
          <line x1={0} x2={plotWidth} y1={zeroY} y2={zeroY} stroke="var(--color-warm-300)" strokeWidth={1} />
        </g>
      </svg>
      {hoverIndex !== null && (
        <div className="absolute top-1 right-1 bg-white border border-warm-150 rounded-md px-2 py-1 text-xs text-warm-800 shadow-sm pointer-events-none">
          <div className="text-warm-400">{data[hoverIndex].label}</div>
          <div className="tabular-nums font-medium">{formatValue(data[hoverIndex].value)}</div>
        </div>
      )}
    </div>
  );
}
