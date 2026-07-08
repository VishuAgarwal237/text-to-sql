"""Pipeline nodes + a framework-agnostic runner.

Each node is a pure function `(state, resources) -> partial_state_update`. `run_pipeline` wires
them together in plain Python with the same routing the LangGraph adapter uses, so the whole
pipeline runs and is testable without langgraph installed. `app/graph.py` is a thin adapter that
registers these same functions as a `StateGraph`.

Deterministic nodes (validate, execute) call `app/db.py` / `app/execution.py` directly; generative
nodes (router, hydration finalize, sql, repair, presentation) call `resources.complete_fn`.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import sqlglot

from app import db, execution, llm
from app.agents import hydration
from app.execution import QueryCostError, QueryTimeout
from app.state import AgentState, Resources


def _trace(state: AgentState, name: str) -> list[str]:
    return state.get("trace", []) + [name]


# --- generative + deterministic nodes ------------------------------------------------------
def router_node(state: AgentState, res: Resources) -> dict[str, Any]:
    data = llm.parse_json(res.complete_fn(res.prompt("router"), state["question"]))
    return {
        "intent": data.get("intent", "unsupported"),
        "entities": data.get("entities", {}),
        "router_message": data.get("result", ""),
        "trace": _trace(state, "router"),
    }


def hydrate_node(state: AgentState, res: Resources) -> dict[str, Any]:
    h = hydration.hydrate(
        state["question"],
        state.get("entities", {}),
        res.catalog,
        res.embed_index,
        res.value_index,
        res.fk_graph,
        complete_fn=res.complete_fn,
        embed_fn=res.embed_fn,
        candidate_k=res.candidate_k,
        budget_tokens=res.budget_tokens,
    )
    return {"hydration": h, "trace": _trace(state, "hydrate")}


def generate_sql_node(state: AgentState, res: Resources) -> dict[str, Any]:
    ctx = state["hydration"].get("schema_context", "")
    user = f"## Question\n{state['question']}\n\n## Hydrated schema context\n{ctx}\n"
    data = llm.parse_json(res.complete_fn(res.prompt("sql_generation"), user))
    return {
        "sql": data.get("sql", ""),
        "assumptions": data.get("assumptions", []),
        "trace": _trace(state, "generate_sql"),
    }


def validate_node(state: AgentState, res: Resources) -> dict[str, Any]:
    """Deterministic: read-only guard + sqlglot parse + EXPLAIN dry-run. Sets validation_error."""
    sql = state.get("sql", "")
    err: str | None = None
    try:
        db.assert_read_only(sql)
        sqlglot.parse_one(sql, read="sqlite")  # syntactic parse
        db.explain(sql)  # binds against the live schema without executing
    except (db.UnsafeSQLError, sqlite3.Error, sqlglot.errors.ParseError) as e:
        err = f"{type(e).__name__}: {e}"
    return {"validation_error": err, "trace": _trace(state, "validate")}


def repair_node(state: AgentState, res: Resources) -> dict[str, Any]:
    ctx = state.get("hydration", {}).get("schema_context", "")
    retries = state.get("retries", 0)
    user = (
        f"## Original question\n{state['question']}\n\n"
        f"## Hydrated schema context\n{ctx}\n\n"
        f"## Previous SQL\n{state.get('sql', '')}\n\n"
        f"## Error\n{state.get('validation_error', '')}\n\n"
        f"## Retry {retries + 1} of {res.max_retries}\n"
    )
    data = llm.parse_json(res.complete_fn(res.prompt("repair"), user))
    return {
        "sql": data.get("sql", state.get("sql", "")),
        "retries": retries + 1,
        "validation_error": None,
        "trace": _trace(state, "repair"),
    }


def execute_node(state: AgentState, res: Resources) -> dict[str, Any]:
    """Guarded execution. On failure, set validation_error so routing sends it back to repair."""
    try:
        result = execution.run_guarded(state["sql"], res.max_rows, res.timeout_ms)
        return {"result": result, "validation_error": None, "trace": _trace(state, "execute")}
    except (db.UnsafeSQLError, QueryCostError, QueryTimeout, sqlite3.Error) as e:
        return {
            "validation_error": f"{type(e).__name__}: {e}",
            "trace": _trace(state, "execute"),
        }


def _infer_types(columns: list[str], rows: list[dict]) -> dict[str, str]:
    types: dict[str, str] = {}
    for c in columns:
        val = next((r[c] for r in rows if r.get(c) is not None), None)
        if isinstance(val, (int, float)):
            types[c] = "numeric"
        elif val is None:
            types[c] = "unknown"
        else:
            types[c] = "categorical"
    return types


def present_node(state: AgentState, res: Resources) -> dict[str, Any]:
    result = state["result"]
    user = (
        f"## Question\n{state['question']}\n\n"
        f"## Executed SQL (for grounding only)\n{state.get('sql', '')}\n\n"
        f"## Columns and inferred types\n"
        f"{json.dumps(_infer_types(result['columns'], result['rows']))}\n\n"
        f"## Rows (sample)\n{json.dumps(result['rows'][:20], default=str)}\n\n"
        f"## Row count: {result['row_count']} | truncated: {result['truncated']}\n"
    )
    data = llm.parse_json(res.complete_fn(res.prompt("presentation"), user))
    return {"presentation": data, "trace": _trace(state, "present")}


def aggregate_node(state: AgentState, res: Resources) -> dict[str, Any]:
    """Assemble the final user-facing answer. Handles both the SQL path and the meta/error path."""
    if state.get("intent") != "analytical_sql":
        answer = {"kind": state.get("intent"), "message": state.get("router_message", "")}
        return {"answer": answer, "trace": _trace(state, "aggregate")}

    pres = state.get("presentation", {})
    result = state.get("result", {})
    answer = {
        "kind": "analytical_sql",
        "summary": pres.get("summary"),
        "sql": state.get("sql"),
        "columns": result.get("columns", []),
        "rows": result.get("rows", []),
        "row_count": result.get("row_count", 0),
        "truncated": result.get("truncated", False),
        "chart_type": pres.get("chart_type"),
        "chart_spec": pres.get("chart_spec"),
        "assumptions": state.get("assumptions", []),
        "error": state.get("error"),
    }
    return {"answer": answer, "trace": _trace(state, "aggregate")}


# --- routing predicates (shared by run_pipeline and the langgraph adapter) ------------------
def route_after_router(state: AgentState) -> str:
    return "hydrate" if state.get("intent") == "analytical_sql" else "aggregate"


def route_after_validate(state: AgentState, res: Resources) -> str:
    if not state.get("validation_error"):
        return "execute"
    return "repair" if state.get("retries", 0) < res.max_retries else "fail"


def route_after_execute(state: AgentState, res: Resources) -> str:
    if not state.get("validation_error"):
        return "present"
    return "repair" if state.get("retries", 0) < res.max_retries else "fail"


# --- framework-agnostic runner --------------------------------------------------------------
def run_pipeline(question: str, res: Resources) -> AgentState:
    """Execute the whole graph in plain Python (no langgraph). Same routing as the adapter."""
    state: AgentState = {"question": question, "retries": 0, "trace": []}
    state.update(router_node(state, res))
    if route_after_router(state) == "aggregate":
        state.update(aggregate_node(state, res))
        return state

    state.update(hydrate_node(state, res))
    state.update(generate_sql_node(state, res))

    while True:
        state.update(validate_node(state, res))
        branch = route_after_validate(state, res)
        if branch == "repair":
            state.update(repair_node(state, res))
            continue
        if branch == "fail":
            state["error"] = state.get("validation_error")
            break
        # validated → execute
        state.update(execute_node(state, res))
        ebranch = route_after_execute(state, res)
        if ebranch == "present":
            state.update(present_node(state, res))
            break
        if ebranch == "fail":
            state["error"] = state.get("validation_error")
            break
        # execution failed but retries remain → repair, then re-validate
        state.update(repair_node(state, res))

    state.update(aggregate_node(state, res))
    return state
