# Agent System Prompts

These are the system prompts for the LLM-driven agents in the MelodyStream text-to-SQL
LangGraph pipeline. Each follows a shared 6-section contract (Role & Persona · Objective &
Scope · Capabilities & Tools · Operating Rules & Constraints · Chain-of-Thought · JSON Output
Contract) so their outputs flow cleanly through the shared graph state.

## Pipeline order

```
Router → Schema Hydration → SQL Generation → [Validate ⇄ Repair]* → Execute → (Summarize ‖ Visualize) → Aggregate
```

## LLM agents (have a system prompt here)

| Prompt file | Agent | Responsibility |
|---|---|---|
| `router.md` | Router / Intent | Classify request (analytical_sql / clarification / meta / unsupported); extract metrics, dimensions, filters. Keeps garbage out of the SQL path. |
| `schema_hydration.md` | Schema Hydration | Load the metadata catalog, select relevant tables/columns + join paths, resolve business concepts ("revenue" → `SUM(InvoiceLine.UnitPrice*Quantity)`). The biggest accuracy lever. |
| `sql_generation.md` | SQL Generation | Compose one read-only SQLite `SELECT` grounded in the hydrated context + few-shot + dialect rules. |
| `repair.md` | Repair | Given a validation/execution error, produce a corrected query (the self-correcting half of the loop). |
| `summarizer.md` | Summarizer | Turn the result rows into a concise plain-English answer. Runs in parallel with the Visualizer. |
| `visualizer.md` | Visualizer | Decide the chart type (bar/line/scatter/kpi/table) and emit a render-ready chart spec — "who decides the viz." Runs in parallel with the Summarizer. |

## Deterministic agents (no LLM prompt — pure code)

These nodes are implemented in code and intentionally have **no** system prompt, because they must
be exact and cheap, not generative:

| Node | Where | Why no prompt |
|---|---|---|
| **Validation core** | `app/agents/validator.py` (uses `app/db.py`) | sqlglot parse + `EXPLAIN` dry-run + read-only guard. Deterministic checks; on failure it hands the error to the Repair agent above. |
| **Execution** | `app/agents/executor.py` → MCP SQLite server (`app/mcp_server.py`) | Runs the validated read-only query and returns rows + column types. A tool call, not a reasoning step. |
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
