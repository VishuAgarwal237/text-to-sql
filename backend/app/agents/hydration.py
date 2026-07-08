"""Schema Hydration — retrieval-grounded, LLM-decided.

Pipeline (ordered per the design constraint that the **LLM still chooses the tables** and the
deterministic machinery does as little as possible *before* that choice):

  1. retrieval        embedding index → generous top-K candidate tables (recall, not precision)
  2. value linking    value/entity index → tables/columns that literally contain the question's
                      mentioned values; these are force-included in the candidate set
  3. context budget   pack candidate metadata into the token budget → the bundle the LLM reads
  4. LLM finalize     the agent reads the metadata bundle and CHOOSES tables/columns + resolves
                      business concepts  ← the decision lives here, not in code
  5. FK path search   connect the LLM's chosen tables with exact ON clauses + bridge tables

Only step 5 is deterministic table-graph logic, and it runs *after* the LLM has decided. Steps
1-3 exist solely because the full catalog doesn't fit at scale; they widen, they don't decide.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from app import llm
from app.retrieval.embedding_index import TableEmbeddingIndex
from app.retrieval.value_index import ValueIndex
from app.schema import context_budget
from app.schema.fk_graph import FKGraph

_PROMPT = (Path(__file__).parent / "prompts" / "schema_hydration.md").read_text()


def _finalize_user_msg(question: str, entities: dict, bundle: str, value_hints: dict) -> str:
    return (
        f"## Question\n{question}\n\n"
        f"## Router entities\n{json.dumps(entities, indent=2)}\n\n"
        f"## Candidate tables (metadata — choose from these)\n{bundle}\n\n"
        f"## Value hints (literals in the question found in these columns)\n"
        f"{json.dumps(value_hints, indent=2)}\n\n"
        "Choose the tables and columns needed to answer the question and resolve the business "
        "concepts. Do NOT emit join ON clauses — the system computes those from your chosen tables."
    )


def hydrate(
    question: str,
    entities: dict[str, Any],
    catalog: dict[str, Any],
    embed_index: TableEmbeddingIndex,
    value_index: ValueIndex,
    fk_graph: FKGraph,
    *,
    complete_fn: Callable[[str, str], str] = llm.complete,
    candidate_k: int = 30,
    budget_tokens: int = 6000,
) -> dict[str, Any]:
    """Produce the hydrated schema context for the SQL-generation agent."""
    # 1 + 2 — recall-oriented candidate generation. Widen, don't decide.
    ranked = [t for t, _ in embed_index.query(question, k=candidate_k)]
    value_hints = value_index.query(question)
    forced = value_index.candidate_tables(question)  # literal matches must not be budgeted out
    for t in forced:
        if t not in ranked:
            ranked.append(t)

    # 3 — pack the candidate metadata into the prompt budget.
    packed = context_budget.pack(ranked, catalog, budget_tokens, always_include=forced)

    # 4 — the LLM reads the metadata and CHOOSES tables/columns + resolves concepts.
    raw = complete_fn(_PROMPT, _finalize_user_msg(question, entities, packed["bundle"], value_hints))
    decision = llm.parse_json(raw)
    selected_tables: list[str] = decision.get("selected_tables", [])
    selected_columns: dict[str, list[str]] = decision.get("selected_columns", {})

    # 5 — connect the chosen tables deterministically (exact ON clauses + bridges).
    connection = fk_graph.connect(selected_tables)

    # Assemble the schema_context handed downstream. Bridge tables added by the graph are
    # surfaced so the SQL agent knows why an unrequested table appears in the joins.
    schema_context = _assemble_context(catalog, connection, selected_columns, decision)

    return {
        "status": decision.get("status", "success"),
        "selected_tables": connection["tables"],
        "selected_columns": selected_columns,
        "join_clauses": connection["join_clauses"],
        "bridge_tables": connection["bridge_tables"],
        "unconnected_tables": connection["unconnected"],
        "resolved_concepts": decision.get("resolved_concepts", []),
        "resolved_filters": decision.get("resolved_filters", []),
        "dialect_notes": decision.get("dialect_notes", []),
        "value_hints": value_hints,
        "schema_context": schema_context,
        "trace": {
            "candidates": ranked,
            "included_tables": packed["included_tables"],
            "dropped_tables": packed["dropped_tables"],
            "tokens_used": packed["tokens_used"],
        },
    }


def _assemble_context(catalog, connection, selected_columns, decision) -> str:
    lines = ["TABLES & COLUMNS:"]
    for t in connection["tables"]:
        cols = selected_columns.get(t)
        entry = catalog.get("tables", {}).get(t, {})
        if not cols:  # a bridge table the LLM didn't pick columns for — expose its keys
            cols = list(entry.get("columns", {}))[:6]
        lines.append(f"  {t}({', '.join(cols)})")
    if connection["join_clauses"]:
        lines.append("JOINS:")
        lines += [f"  {j}" for j in connection["join_clauses"]]
    if decision.get("resolved_concepts"):
        lines.append("RESOLVED CONCEPTS:")
        for rc in decision["resolved_concepts"]:
            lines.append(f"  {rc.get('phrase')} -> {rc.get('resolution')}")
    if decision.get("resolved_filters"):
        lines.append("RESOLVED FILTERS:")
        for rf in decision["resolved_filters"]:
            lines.append(f"  {rf.get('phrase')} -> {rf.get('predicate')}")
    if decision.get("dialect_notes"):
        lines.append("DIALECT: " + "; ".join(decision["dialect_notes"]))
    if connection["bridge_tables"]:
        lines.append("NOTE: bridge tables added for join connectivity: "
                     + ", ".join(connection["bridge_tables"]))
    return "\n".join(lines)
