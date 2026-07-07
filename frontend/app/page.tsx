"use client";

import { useEffect, useState } from "react";
import ResultChart, { ResultTable } from "@/components/ResultChart";
import { fetchModels, runQuery, type QueryResult } from "@/lib/api";

const SAMPLES = [
  "What are the top 5 best-selling genres by total sales?",
  "How many customers does each country have?",
  "Which employee has the most customers assigned to them?",
  "What is the total revenue generated in the year 2021?",
];

export default function Home() {
  const [question, setQuestion] = useState("");
  const [model, setModel] = useState<string>("");
  const [models, setModels] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<QueryResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sqlOpen, setSqlOpen] = useState(true);

  useEffect(() => {
    fetchModels().then((m) => {
      setModels(m);
      if (m.length) setModel(m[m.length - 1]);
    });
  }, []);

  async function ask(q: string) {
    if (!q.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const r = await runQuery(q, model || undefined);
      setResult(r);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-4xl px-4 py-8">
      <header className="mb-6">
        <h1 className="text-2xl font-bold">🎵 MelodyStream — Ask your data</h1>
        <p className="text-gray-500">
          Ask a question in plain English. Agents interpret it, write validated SQL, run it, and
          summarize + visualize the answer.
        </p>
      </header>

      {/* Question bar */}
      <div className="flex gap-2">
        <input
          className="flex-1 rounded-lg border border-gray-300 px-4 py-3 focus:border-brand focus:outline-none"
          placeholder="e.g. What are the top-selling genres in Germany?"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && ask(question)}
        />
        {models.length > 0 && (
          <select
            className="rounded-lg border border-gray-300 px-2 text-sm"
            value={model}
            onChange={(e) => setModel(e.target.value)}
          >
            {models.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        )}
        <button
          className="rounded-lg bg-brand px-5 py-3 font-semibold text-white hover:bg-brand-light disabled:opacity-50"
          onClick={() => ask(question)}
          disabled={loading}
        >
          {loading ? "Thinking…" : "Ask"}
        </button>
      </div>

      {/* Sample chips */}
      <div className="mt-3 flex flex-wrap gap-2">
        {SAMPLES.map((s) => (
          <button
            key={s}
            className="rounded-full border border-gray-300 px-3 py-1 text-xs text-gray-600 hover:border-brand hover:text-brand"
            onClick={() => {
              setQuestion(s);
              ask(s);
            }}
          >
            {s}
          </button>
        ))}
      </div>

      {error && (
        <div className="mt-6 rounded-lg border border-red-200 bg-red-50 p-4 text-red-700">
          {error}
        </div>
      )}

      {result && (
        <div className="mt-6 space-y-4">
          {/* Question banner */}
          <div className="rounded-t-lg bg-gradient-to-r from-brand to-brand-light px-5 py-4 font-medium text-white">
            {result.question}
          </div>

          {/* Clarification / non-SQL intents */}
          {result.status === "pending_user_input" && (
            <Card icon="❓" title="Clarification needed">
              <p>{result.clarification || result.summary}</p>
            </Card>
          )}
          {result.status === "error" && (
            <Card icon="⚠️" title="Could not answer">
              <p className="text-red-600">{result.error}</p>
            </Card>
          )}

          {result.status === "success" && result.intent === "analytical_sql" && (
            <>
              {/* Summary */}
              <Card icon="💬" title="Summary">
                <p className="leading-relaxed">{result.summary}</p>
              </Card>

              {/* SQL (collapsible) */}
              <Card
                icon="📝"
                title="SQL Query"
                right={
                  <button className="text-gray-400" onClick={() => setSqlOpen(!sqlOpen)}>
                    {sqlOpen ? "▲" : "▼"}
                  </button>
                }
              >
                {sqlOpen && (
                  <pre className="overflow-x-auto rounded bg-gray-900 p-4 text-sm text-gray-100">
                    {result.sql}
                  </pre>
                )}
              </Card>

              {/* Results table */}
              <Card icon="📊" title={`Results (${result.row_count} rows)`}>
                <ResultTable rows={result.rows} columns={result.columns} />
              </Card>

              {/* Auto-selected chart */}
              <Card icon="📈" title={result.chart_spec?.title || "Query Results"}>
                <ResultChart spec={result.chart_spec} rows={result.rows} columns={result.columns} />
                <p className="mt-2 text-xs text-gray-400">
                  Chart type <b>{result.chart_type}</b> chosen automatically for this result shape.
                </p>
              </Card>
            </>
          )}

          {result.status === "success" && result.intent !== "analytical_sql" && (
            <Card icon="💬" title="Response">
              <p>{result.summary}</p>
            </Card>
          )}

          {/* Trace / metrics */}
          <div className="flex flex-wrap gap-4 rounded-lg bg-gray-100 px-4 py-3 text-xs text-gray-500">
            <span>model: <b>{result.model}</b></span>
            <span>retries: {result.retries}</span>
            <span>llm: {result.llm_seconds?.toFixed(2)}s</span>
            <span>wall: {result.wall_clock_s?.toFixed(2)}s</span>
            <span>cost: ${result.cost_usd?.toFixed(4)}</span>
            <span>steps: {result.trace?.map((t) => t.step).join(" → ")}</span>
          </div>
        </div>
      )}
    </main>
  );
}

function Card({
  icon,
  title,
  right,
  children,
}: {
  icon: string;
  title: string;
  right?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border border-gray-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-gray-100 px-5 py-3">
        <h2 className="font-semibold">
          <span className="mr-2">{icon}</span>
          {title}
        </h2>
        {right}
      </div>
      <div className="px-5 py-4">{children}</div>
    </section>
  );
}
