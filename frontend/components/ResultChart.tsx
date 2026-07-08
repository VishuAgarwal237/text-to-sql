"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ChartSpec } from "@/lib/api";

// Analog-console series palette: amber, signal-cyan, magenta, lime, violet.
const COLORS = ["#F6A93B", "#5BD1E6", "#D774A8", "#A8D65C", "#8B7FD6"];
const AXIS = "#A79FB2";
const GRID = "#332E3D";

const tooltipStyle = {
  background: "#1E1B25",
  border: "1px solid #332E3D",
  borderRadius: 10,
  color: "#F4EFE6",
  fontSize: 12,
  fontFamily: "var(--font-mono), monospace",
} as const;

export default function ResultChart({
  spec,
  rows,
  columns,
}: {
  spec: ChartSpec;
  rows: Record<string, unknown>[];
  columns: string[];
}) {
  if (!rows.length) return <p className="text-sm text-fog">No results to display.</p>;

  // KPI card — single scalar
  if (spec.type === "kpi") {
    const key = spec.y?.[0] || columns[0];
    const value = rows[0]?.[key];
    return (
      <div className="flex flex-col items-center justify-center py-10">
        <div className="font-display text-6xl font-semibold text-amber">{String(value)}</div>
        <div className="mt-2 font-mono text-[11px] uppercase tracking-[0.18em] text-fog">{key}</div>
      </div>
    );
  }

  // Table fallback
  if (spec.type === "table") {
    return <ResultTable rows={rows} columns={columns} />;
  }

  const x = spec.x || columns[0];
  const ys = spec.y && spec.y.length ? spec.y : [columns[1]];

  return (
    <ResponsiveContainer width="100%" height={380}>
      {spec.type === "line" ? (
        <LineChart data={rows} margin={{ top: 10, right: 20, bottom: 60, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID} />
          <XAxis dataKey={x} angle={-35} textAnchor="end" height={70} tick={{ fontSize: 12, fill: AXIS }} stroke={GRID} />
          <YAxis tick={{ fontSize: 12, fill: AXIS }} stroke={GRID} />
          <Tooltip contentStyle={tooltipStyle} cursor={{ stroke: GRID }} />
          {ys.map((y, i) => (
            <Line key={y} type="monotone" dataKey={y} stroke={COLORS[i % COLORS.length]} strokeWidth={2} dot={false} />
          ))}
        </LineChart>
      ) : spec.type === "scatter" ? (
        <ScatterChart margin={{ top: 10, right: 20, bottom: 60, left: 0 }}>
          <CartesianGrid stroke={GRID} />
          <XAxis dataKey={x} name={x} tick={{ fontSize: 12, fill: AXIS }} stroke={GRID} />
          <YAxis dataKey={ys[0]} name={ys[0]} tick={{ fontSize: 12, fill: AXIS }} stroke={GRID} />
          <Tooltip contentStyle={tooltipStyle} cursor={{ strokeDasharray: "3 3", stroke: GRID }} />
          <Scatter data={rows} fill={COLORS[0]} />
        </ScatterChart>
      ) : (
        <BarChart data={rows} margin={{ top: 10, right: 20, bottom: 70, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={GRID} vertical={false} />
          <XAxis dataKey={x} angle={-35} textAnchor="end" height={80} interval={0} tick={{ fontSize: 11, fill: AXIS }} stroke={GRID} />
          <YAxis tick={{ fontSize: 12, fill: AXIS }} stroke={GRID} />
          <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "rgba(246,169,59,0.08)" }} />
          {ys.map((y, i) => (
            <Bar key={y} dataKey={y} fill={COLORS[i % COLORS.length]} radius={[3, 3, 0, 0]} />
          ))}
        </BarChart>
      )}
    </ResponsiveContainer>
  );
}

export function ResultTable({
  rows,
  columns,
}: {
  rows: Record<string, unknown>[];
  columns: string[];
}) {
  const cols = columns.length ? columns : Object.keys(rows[0] || {});
  return (
    <div className="max-h-96 overflow-auto rounded-lg border border-line">
      <table className="w-full border-collapse text-sm">
        <thead className="sticky top-0 bg-raise">
          <tr>
            {cols.map((c) => (
              <th
                key={c}
                className="border-b border-line px-3 py-2.5 text-left font-mono text-[11px] uppercase tracking-[0.12em] text-fog"
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="odd:bg-panel/40 hover:bg-raise/60">
              {cols.map((c) => (
                <td key={c} className="border-b border-line/60 px-3 py-2 text-cream">
                  {String(r[c] ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
