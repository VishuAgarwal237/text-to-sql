"use client";

import { Fragment, useEffect, useState } from "react";
import ResultChart, { ResultTable } from "@/components/ResultChart";
import { fetchModels, runQuery, type QueryResult } from "@/lib/api";

const SAMPLES = [
  "Top 5 best-selling genres by total sales",
  "How many customers does each country have?",
  "Which employee has the most customers assigned?",
  "Total revenue generated in 2021",
];

// Friendly names for the agent pipeline nodes — the trace is a real sequence (a signal chain).
const STEP_LABEL: Record<string, string> = {
  router: "Intent",
  schema_hydration: "Schema",
  sql_generation: "SQL",
  validate: "Validate",
  validation: "Validate",
  repair: "Repair",
  execute: "Execute",
  execution: "Execute",
  summarize: "Summary",
  summarizer: "Summary",
  visualize: "Chart",
  visualizer: "Chart",
  aggregate: "Assemble",
};
const stepName = (s: string) => STEP_LABEL[s] ?? s.replace(/_/g, " ");

function Eq({ className = "" }: { className?: string }) {
  return (
    <span className={`eq ${className}`} aria-hidden="true">
      <i /><i /><i /><i /><i />
    </span>
  );
}

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
    if (!q.trim() || loading) return;
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
    <main className="mx-auto max-w-5xl px-5 py-10 sm:px-8 sm:py-14">
      {/* Masthead */}
      <header className="flex flex-wrap items-end justify-between gap-4 border-b border-line pb-6">
        <div>
          <div className="flex items-center gap-3">
            <Eq className="h-6 text-amber" />
            <h1 className="font-display text-3xl font-semibold tracking-tight text-cream sm:text-4xl">
              MelodyStream
            </h1>
            <span className="mt-1 hidden font-mono text-[10.5px] uppercase tracking-[0.22em] text-fog sm:inline">
              text-to-sql
            </span>
          </div>
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-fog">
            Ask the music catalog anything. A relay of agents reads your intent, writes validated
            SQL, runs it read-only, then summarizes and charts the answer.
          </p>
        </div>
        <span className="flex items-center gap-2 rounded-full border border-line bg-panel px-3 py-1.5 font-mono text-[11px] text-fog">
          <span className="h-1.5 w-1.5 rounded-full bg-signal shadow-[0_0_8px_#5BD1E6]" />
          Chinook · SQLite · read-only
        </span>
      </header>

      {/* Console — the query input */}
      <section className="mt-8">
        <label htmlFor="q" className="eyebrow">
          Ask
        </label>
        <div className="mt-2 flex flex-col gap-2 rounded-xl border border-line bg-panel/80 p-2 backdrop-blur-sm transition-colors focus-within:border-amber/60 sm:flex-row">
          <input
            id="q"
            className="min-w-0 flex-1 bg-transparent px-3 py-3 text-[15px] text-cream placeholder:text-fog/60 focus:outline-none"
            placeholder="e.g. What are the top-selling genres in Germany?"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && ask(question)}
          />
          <div className="flex items-center gap-2">
            {models.length > 0 && (
              <select
                className="rounded-lg border border-line bg-raise px-2.5 py-2.5 font-mono text-xs text-fog focus:border-amber/60 focus:outline-none"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                aria-label="Model"
              >
                {models.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            )}
            <button
              className="flex items-center gap-2 rounded-lg bg-amber px-5 py-2.5 text-sm font-semibold text-ink transition-colors hover:bg-amber-deep disabled:cursor-not-allowed disabled:opacity-60"
              onClick={() => ask(question)}
              disabled={loading}
            >
              {loading ? (
                <>
                  <Eq className="h-3.5 text-ink" /> Reading
                </>
              ) : (
                "Ask"
              )}
            </button>
          </div>
        </div>

        {/* Sample crate */}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span className="eyebrow mr-1">Try</span>
          {SAMPLES.map((s) => (
            <button
              key={s}
              className="rounded-full border border-line bg-panel/60 px-3 py-1.5 text-xs text-fog transition-colors hover:border-amber/50 hover:text-cream"
              onClick={() => {
                setQuestion(s);
                ask(s);
              }}
            >
              {s}
            </button>
          ))}
        </div>
      </section>

      {/* Fetch-level error */}
      {error && (
        <Panel label="Connection error" className="mt-8 border-amber/40">
          <p className="text-sm text-cream">Couldn&apos;t reach the query service.</p>
          <p className="mt-1 font-mono text-xs text-fog">{error}</p>
        </Panel>
      )}

      {/* Working state */}
      {loading && (
        <div className="mt-8 flex items-center gap-4 rounded-xl border border-line bg-panel/60 px-6 py-8">
          <Eq className="h-7 text-amber" />
          <div>
            <p className="font-display text-lg text-cream">Composing the answer…</p>
            <p className="mt-0.5 font-mono text-[11px] uppercase tracking-[0.18em] text-fog">
              intent → schema → sql → validate → execute → summarize
            </p>
          </div>
        </div>
      )}

      {/* Empty invitation */}
      {!loading && !result && !error && (
        <div className="mt-10 rounded-xl border border-dashed border-line bg-panel/30 px-6 py-16 text-center">
          <Eq className="mx-auto h-8 text-line" />
          <p className="mt-4 font-display text-xl text-cream">Nothing on the deck yet</p>
          <p className="mx-auto mt-1 max-w-sm text-sm text-fog">
            Ask about sales, artists, genres, customers, or revenue — or drop the needle on a sample
            above.
          </p>
        </div>
      )}

      {/* Result */}
      {result && (
        <div className="mt-8 space-y-4">
          {/* Now playing — the question */}
          <div className="animate-fade-up">
            <span className="eyebrow">Now querying</span>
            <p className="mt-1 font-display text-xl italic text-cream sm:text-2xl">
              {result.question}
            </p>
          </div>

          {result.status === "pending_user_input" && (
            <Panel label="Clarification needed">
              <p className="text-sm leading-relaxed text-cream">
                {result.clarification || result.summary}
              </p>
            </Panel>
          )}

          {result.status === "error" && (
            <Panel label="Couldn't answer" className="border-amber/40">
              <p className="text-sm leading-relaxed text-cream">{result.error}</p>
            </Panel>
          )}

          {result.status === "success" && result.intent === "analytical_sql" && (
            <>
              <Panel label="Summary">
                <p className="text-[15px] leading-relaxed text-cream">{result.summary}</p>
              </Panel>

              <Panel
                label="SQL"
                right={
                  <button
                    className="font-mono text-[11px] uppercase tracking-[0.18em] text-fog transition-colors hover:text-amber"
                    onClick={() => setSqlOpen(!sqlOpen)}
                  >
                    {sqlOpen ? "Hide" : "Show"}
                  </button>
                }
              >
                {sqlOpen && (
                  <pre className="overflow-x-auto rounded-lg border border-line bg-ink px-4 py-3.5 font-mono text-[13px] leading-relaxed text-signal">
                    {result.sql}
                  </pre>
                )}
              </Panel>

              <Panel label={`Results · ${result.row_count} ${result.row_count === 1 ? "row" : "rows"}`}>
                <ResultTable rows={result.rows} columns={result.columns} />
              </Panel>

              <Panel label={result.chart_spec?.title || "Visual"} right={
                <span className="font-mono text-[11px] uppercase tracking-[0.18em] text-fog">
                  {result.chart_type}
                </span>
              }>
                <ResultChart spec={result.chart_spec} rows={result.rows} columns={result.columns} />
              </Panel>
            </>
          )}

          {result.status === "success" && result.intent !== "analytical_sql" && (
            <Panel label="Response">
              <p className="text-sm leading-relaxed text-cream">{result.summary}</p>
            </Panel>
          )}

          {/* Signal chain + tape counter */}
          {result.trace && result.trace.length > 0 && (
            <div className="animate-fade-up rounded-xl border border-line bg-panel/50 px-5 py-4">
              <span className="eyebrow">Signal chain</span>
              <div className="mt-2.5 flex flex-wrap items-center gap-x-1.5 gap-y-2">
                {result.trace.map((t, i) => (
                  <Fragment key={i}>
                    {i > 0 && <span className="text-line">→</span>}
                    <span className="rounded-md border border-line bg-raise px-2.5 py-1 font-mono text-[11px] text-fog">
                      {stepName(t.step)}
                    </span>
                  </Fragment>
                ))}
              </div>
              <div className="mt-4 flex flex-wrap gap-x-6 gap-y-1.5 border-t border-line pt-3 font-mono text-[11px]">
                <Readout label="model" value={result.model ?? "—"} />
                <Readout label="retries" value={String(result.retries ?? 0)} />
                <Readout label="llm" value={`${result.llm_seconds?.toFixed(2) ?? "—"}s`} />
                <Readout label="wall" value={`${result.wall_clock_s?.toFixed(2) ?? "—"}s`} />
                <Readout label="cost" value={`$${result.cost_usd?.toFixed(4) ?? "—"}`} />
              </div>
            </div>
          )}
        </div>
      )}

      <footer className="mt-16 border-t border-line pt-5 font-mono text-[11px] text-fog/70">
        MelodyStream — agentic natural-language-to-SQL over the Chinook catalog
      </footer>
    </main>
  );
}

function Panel({
  label,
  right,
  children,
  className = "",
}: {
  label: string;
  right?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`animate-fade-up overflow-hidden rounded-xl border border-line bg-panel/80 backdrop-blur-sm ${className}`}
    >
      <div className="flex items-center justify-between gap-3 border-b border-line px-5 py-3">
        <span className="eyebrow">{label}</span>
        {right}
      </div>
      <div className="px-5 py-4">{children}</div>
    </section>
  );
}

function Readout({ label, value }: { label: string; value: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="text-fog/60">{label}</span>
      <span className="text-cream">{value}</span>
    </span>
  );
}
