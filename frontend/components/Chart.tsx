"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ChartSpec } from "@/lib/api";

// Single-series charts only (one question -> one result set), so per the
// dataviz skill: one hue, no legend needed (the heading above the chart
// names the series), thin marks with rounded data-ends, recessive
// gridlines/axes. Colors come from CSS custom properties defined on
// .viz-root in globals.css (the validated default palette), not hardcoded
// here, so light/dark mode swap in one place.

function truncateLabel(label: string, max = 14): string {
  return label.length > max ? `${label.slice(0, max - 1)}…` : label;
}

function TooltipContent({
  active,
  payload,
  xField,
  yField,
}: {
  active?: boolean;
  payload?: { payload: Record<string, string | number> }[];
  xField: string;
  yField: string;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const point = payload[0].payload;
  return (
    <div
      style={{
        background: "var(--viz-surface)",
        border: "1px solid var(--viz-gridline)",
        borderRadius: 6,
        padding: "6px 10px",
        fontSize: 12,
        color: "var(--viz-text-primary)",
        boxShadow: "0 2px 8px rgba(0,0,0,0.12)",
      }}
    >
      <div style={{ color: "var(--viz-text-secondary)" }}>{xField}</div>
      <div style={{ fontWeight: 600 }}>{String(point[xField])}</div>
      <div style={{ marginTop: 4, color: "var(--viz-text-secondary)" }}>{yField}</div>
      <div style={{ fontWeight: 600 }}>{String(point[yField])}</div>
    </div>
  );
}

export default function Chart({ spec }: { spec: ChartSpec }) {
  const xField = spec.x.field;
  const yField = spec.y.field;

  return (
    <div className="viz-root" style={{ width: "100%", height: 280 }}>
      <ResponsiveContainer width="100%" height="100%">
        {spec.type === "bar" ? (
          <BarChart data={spec.data} margin={{ top: 8, right: 8, left: 8, bottom: 8 }}>
            <CartesianGrid
              vertical={false}
              stroke="var(--viz-gridline)"
              strokeDasharray="0"
            />
            <XAxis
              dataKey={xField}
              tickFormatter={(v) => truncateLabel(String(v))}
              tick={{ fill: "var(--viz-muted)", fontSize: 11 }}
              axisLine={{ stroke: "var(--viz-baseline)" }}
              tickLine={false}
            />
            <YAxis
              tick={{ fill: "var(--viz-muted)", fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              width={56}
            />
            <Tooltip
              content={<TooltipContent xField={xField} yField={yField} />}
              cursor={{ fill: "var(--viz-gridline)", opacity: 0.4 }}
            />
            <Bar
              dataKey={yField}
              fill="var(--viz-series-1)"
              radius={[4, 4, 0, 0]}
              maxBarSize={48}
            />
          </BarChart>
        ) : (
          <ScatterChart margin={{ top: 8, right: 8, left: 8, bottom: 8 }}>
            <CartesianGrid stroke="var(--viz-gridline)" strokeDasharray="0" />
            <XAxis
              dataKey={xField}
              type="number"
              name={xField}
              tick={{ fill: "var(--viz-muted)", fontSize: 11 }}
              axisLine={{ stroke: "var(--viz-baseline)" }}
              tickLine={false}
            />
            <YAxis
              dataKey={yField}
              type="number"
              name={yField}
              tick={{ fill: "var(--viz-muted)", fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              width={56}
            />
            <Tooltip
              content={<TooltipContent xField={xField} yField={yField} />}
              cursor={{ stroke: "var(--viz-baseline)", strokeDasharray: "3 3" }}
            />
            <Scatter data={spec.data} fill="var(--viz-series-1)" />
          </ScatterChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}
