# MelodyStream — Agentic Text-to-SQL BI

Natural-language → SQL over the Chinook music-store database, built as a **multi-agent
LangGraph pipeline** with a self-correcting SQL repair loop, a read-only MCP SQLite execution
layer, automatic visualization, a **Braintrust** evaluation harness with a multi-model
accuracy benchmark, and a **Next.js** UI.

Ask a question in plain English → agents interpret intent, hydrate schema metadata, generate
validated SQL, execute it read-only, and return a **summary + the SQL + a results table + an
auto-selected chart**.

## Architecture

```
Router → Schema Hydration → SQL Generation → [Validate ⇄ Repair]* → Execute (MCP SQLite)
                                                                         │
                                          ┌──────────────────────────────┴───────────┐
                                          ▼ (parallel)                                ▼
                                     Summarizer                                  Visualizer
                                          └──────────────────┬─────────────────────┘
                                                             ▼
                                                        Aggregator → {summary, sql, rows, chart, trace}
```

- **Agents & prompts:** `backend/app/agents/` (nodes) + `backend/app/agents/prompts/` (system prompts).
- **Metadata catalog:** `backend/metadata/` — the LLM-generation prompt (`metadata_prompt.md`),
  the generator (`generate_metadata.py`), and the catalog (`schema_metadata.json`).
- **Read-only safety:** `backend/app/db.py` guard + `backend/app/mcp_server.py` MCP server.
- **Eval (Braintrust):** `backend/eval/` — scorers, dataset seeder, per-model runner, report.
- **UI:** `frontend/` (Next.js + Recharts).

## Quick start (Docker)

```bash
./setup.sh                      # downloads data/Chinook.db
cp .env.example .env            # add your ANTHROPIC_API_KEY / FIREWORKS_API_KEY
docker compose up --build
# UI:  http://localhost:3000     API: http://localhost:8000/health
```

No API key handy? Run an **offline demo** with the deterministic stub backend:

```bash
LLM_BACKEND=stub docker compose up --build
```

## Quick start (local, no Docker)

```bash
./setup.sh
cd backend
uv venv && source .venv/bin/activate
uv pip install -e .

# Run the API (add a key, or use the stub)
LLM_BACKEND=stub uvicorn app.main:app --reload         # offline demo
# ANTHROPIC_API_KEY=... DEFAULT_MODEL=anthropic/claude-sonnet-5 uvicorn app.main:app --reload

# Frontend (separate terminal)
cd ../frontend && npm install && npm run dev
```

## Evaluation (the graded core)

```bash
cd backend
# Offline (deterministic) run across the 3 benchmarked models:
LLM_BACKEND=stub python eval/run_eval.py
python eval/report.py            # writes EVAL_REPORT.md + a confusion-matrix PNG

# Real run + Braintrust experiments (side-by-side model comparison in the Braintrust UI):
BRAINTRUST_API_KEY=... ANTHROPIC_API_KEY=... python eval/seed_dataset.py
BRAINTRUST_API_KEY=... ANTHROPIC_API_KEY=... EVAL_MODELS=claude-haiku-4-5,claude-sonnet-5 python eval/run_eval.py
python eval/report.py
```

**Metrics:** execution accuracy (order-insensitive result-set match — the fair metric), valid-SQL
rate, per-category accuracy, cost, and latency. See `EVAL_REPORT.md`.

## Regenerating the metadata catalog (RTF 2.2)

The prompt used to build the catalog is saved for review at `backend/metadata/metadata_prompt.md`.
To regenerate `schema_metadata.json` with an LLM:

```bash
cd backend
ANTHROPIC_API_KEY=... METADATA_MODEL=anthropic/claude-sonnet-5 python metadata/generate_metadata.py
```

## Configuration

All config is env-driven — see `.env.example`. Key switches: `LLM_BACKEND` (`litellm`|`stub`),
`DEFAULT_MODEL`, `EXEC_BACKEND` (`direct`|`mcp`), provider keys, `BRAINTRUST_API_KEY`, `EVAL_MODELS`.

## Safety

Every query path goes through a read-only guard (`app/db.py`): only single `SELECT`/`WITH`
statements run; `INSERT/UPDATE/DELETE/DDL/PRAGMA`/stacked statements are rejected. The database
is also opened in SQLite read-only URI mode, and (in `mcp` mode) executed behind a separate MCP
process.
