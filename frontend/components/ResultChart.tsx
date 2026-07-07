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

const COLORS = ["#4FA9E8", "#F26722", "#34C759", "#AF52DE", "#FF9500"];

export default function ResultChart({
  spec,
  rows,
  columns,
}: {
  spec: ChartSpec;
  rows: Record<string, unknown>[];
  columns: string[];
}) {
  if (!rows.length) return <p className="text-gray-500">No results to display.</p>;

  // KPI card — single scalar
  if (spec.type === "kpi") {
    const key = spec.y?.[0] || columns[0];
    const value = rows[0]?.[key];
    return (
      <div className="flex flex-col items-center justify-center py-10">
        <div className="text-5xl font-bold text-brand">{String(value)}</div>
        <div className="mt-2 text-gray-500">{key}</div>
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
          <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
          <XAxis dataKey={x} angle={-35} textAnchor="end" height={70} tick={{ fontSize: 12 }} />
          <YAxis tick={{ fontSize: 12 }} />
          <Tooltip />
          {ys.map((y, i) => (
            <Line key={y} type="monotone" dataKey={y} stroke={COLORS[i % COLORS.length]} dot={false} />
          ))}
        </LineChart>
      ) : spec.type === "scatter" ? (
        <ScatterChart margin={{ top: 10, right: 20, bottom: 60, left: 0 }}>
          <CartesianGrid stroke="#eee" />
          <XAxis dataKey={x} name={x} tick={{ fontSize: 12 }} />
          <YAxis dataKey={ys[0]} name={ys[0]} tick={{ fontSize: 12 }} />
          <Tooltip cursor={{ strokeDasharray: "3 3" }} />
          <Scatter data={rows} fill={COLORS[0]} />
        </ScatterChart>
      ) : (
        <BarChart data={rows} margin={{ top: 10, right: 20, bottom: 70, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#eee" />
          <XAxis dataKey={x} angle={-35} textAnchor="end" height={80} interval={0} tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 12 }} />
          <Tooltip />
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
    <div className="max-h-96 overflow-auto rounded border border-gray-200">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-gray-50">
          <tr>
            {cols.map((c) => (
              <th key={c} className="px-3 py-2 text-left font-semibold text-gray-700">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-t border-gray-100">
              {cols.map((c) => (
                <td key={c} className="px-3 py-1.5 text-gray-800">
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
