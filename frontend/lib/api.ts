export type ChartSpec = {
  type: "bar" | "line" | "scatter" | "kpi" | "table";
  x?: string | null;
  y?: string[];
  series?: string | null;
  title?: string;
};

export type QueryResult = {
  question: string;
  status: "success" | "error" | "pending_user_input";
  intent: string;
  error?: string | null;
  clarification?: string | null;
  sql: string;
  summary: string;
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  truncated: boolean;
  chart_type: string;
  chart_spec: ChartSpec;
  model?: string;
  retries?: number;
  cost_usd?: number;
  llm_seconds?: number;
  wall_clock_s?: number;
  trace?: { step: string; [k: string]: unknown }[];
};

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function runQuery(question: string, model?: string): Promise<QueryResult> {
  const res = await fetch(`${API_URL}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, model }),
  });
  if (!res.ok) throw new Error(`API error ${res.status}`);
  return res.json();
}

export async function fetchModels(): Promise<string[]> {
  try {
    const res = await fetch(`${API_URL}/health`);
    const j = await res.json();
    return j.models || [];
  } catch {
    return [];
  }
}
