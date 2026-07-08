# Agent System Prompts

These are the system prompts for the LLM-driven agents in the MelodyStream text-to-SQL
LangGraph pipeline. Each follows a shared 6-section contract (Role & Persona · Objective &
Scope · Capabilities & Tools · Operating Rules & Constraints · Chain-of-Thought · JSON Output
Contract) so their outputs flow cleanly through the shared graph state.

## Pipeline order

```
Router → Schema Hydration → SQL Generation → [Validate ⇄ Repair]* → Execute → Presentation → Aggregate
                │
                └─ Retrieval (embed top-K) + Value-linking → Context-budget pack
                   → LLM chooses tables/columns → FK-graph computes joins
```

Schema Hydration is not a single LLM call — it is a retrieval-grounded subgraph. The full catalog
is far too large to hand a model at scale, so retrieval produces a bounded candidate set, the LLM
**chooses** from that set's metadata, and the FK graph deterministically computes the joins for the
tables it chose. See `app/agents/hydration.py`.

## LLM agents (have a system prompt here)

| Prompt file | Agent | Responsibility |
|---|---|---|
| `router.md` | Router / Intent | Classify request (analytical_sql / clarification / meta / unsupported); extract metrics, dimensions, filters. Keeps garbage out of the SQL path. |
| `schema_hydration.md` | Schema Hydration | Reads a **bounded, retrieved** slice of candidate-table metadata (not the whole catalog — see the retrieval pipeline below) plus value-linking hints, then **chooses** the tables/columns and resolves business concepts ("revenue" → `SUM(InvoiceLine.UnitPrice*Quantity)`) and filters ("Germany" → `Customer.Country`). The biggest accuracy lever. It does **not** emit join `ON` clauses — the FK graph computes those. |
| `sql_generation.md` | SQL Generation | Compose one read-only SQLite `SELECT` grounded in the hydrated context + few-shot + dialect rules. |
| `repair.md` | Repair | Given a validation/execution error, produce a corrected query (the self-correcting half of the loop). |
| `presentation.md` | Presentation | In one call, turn the result rows into a concise plain-English summary **and** a render-ready chart spec (bar/line/scatter/kpi/table). The chart type is chosen directly by this agent — there is no separate rule-based recommender. |

## Deterministic agents (no LLM prompt — pure code)

These nodes are implemented in code and intentionally have **no** system prompt, because they must
be exact and cheap, not generative:

| Node | Where | Why no prompt |
|---|---|---|
| **Retrieval (candidate gen)** | `app/retrieval/embedding_index.py` + `value_index.py` | Recall-oriented: embeds the question → generous top-K candidate tables, and value-links literals → the columns that contain them. Widens, doesn't decide — the LLM still chooses. |
| **Context budget** | `app/schema/context_budget.py` | Packs candidate-table metadata into the token budget, highest-ranked first. Owns exactly what goes into the hydration prompt. |
| **FK-graph join search** | `app/schema/fk_graph.py` | Runs *after* the LLM picks tables: connects them with authoritative `ON` clauses (BFS shortest-path union) and adds bridge tables. Not table selection — join computation. |
| **Validation core** | `app/agents/validator.py` (uses `app/db.py`) | sqlglot parse + `EXPLAIN` dry-run + read-only guard. Deterministic checks; on failure it hands the error to the Repair agent above. |
| **Execution (guarded)** | `app/execution.py` (uses `app/db.py`) | Runs the validated query under LIMIT-injection + `EXPLAIN QUERY PLAN` cost check + statement-timeout watchdog + row cap. A tool call, not a reasoning step. |
| **Metadata generation (offline, incremental)** | `app/metadata/generate.py` + `store.py` | Fingerprints each table and regenerates docs only for changed tables; derives relationships from the FK graph. One LLM call per *changed* table, not per table. |
| **Aggregator** | `app/graph.py` (final node) | Assembles `{summary, sql, rows, chart_spec, trace, cost, latency}`. Pure state assembly. |

## Notes

- The prompts are **model-agnostic** — the same prompts run under every benchmarked model
  (a Fireworks OSS model, Claude Haiku 4.5, Claude Sonnet 5) via the LiteLLM gateway, so the eval
  compares models fairly on identical instructions.
- Each agent returns strict JSON matching its Output Contract; the graph parses that JSON into the
  shared `AgentState`. If a model emits malformed JSON, the calling node retries/repairs rather
  than passing bad state downstream.
- The metadata-generation prompt (a separate, offline concern) lives in
  `backend/metadata/metadata_prompt.md`.
