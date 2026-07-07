"""LangGraph assembly for the text-to-SQL pipeline.

Flow:

    router ──analytical?──▶ schema ─▶ sql_generation ─▶ validate ──valid?──▶ execute
      │                                                    ▲   │                 │
      └──meta/clarify/unsupported──▶ aggregate            │   └─invalid & retries left─▶ repair ─┘
                                        ▲                  │        │
                                        │                  └────────┘ (else: aggregate as error)
                                        │
             ┌──────────────────────────┴──────────────────────────┐
   execute ─▶│ summarize ‖ visualize (parallel) │─▶ aggregate ─▶ END │
             └───────────────────────────────────────────────────────┘
"""

from __future__ import annotations

import time
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.executor import execute_node
from app.agents.repair import repair_node
from app.agents.router import route_after_router, router_node
from app.agents.schema import schema_node
from app.agents.sql_generator import sql_generator_node
from app.agents.summarizer import summarizer_node
from app.agents.validator import route_after_validation, validator_node
from app.agents.visualizer import visualizer_node
from app.llm import DEFAULT_MODEL, MODEL_REGISTRY
from app.state import AgentState


def aggregate_node(state: AgentState) -> dict[str, Any]:
    """Assemble the final response payload from whatever the pipeline produced."""
    intent = state.get("intent", "analytical_sql")

    if intent == "clarification_needed":
        status, error = "pending_user_input", None
    elif intent in {"meta", "unsupported"}:
        status, error = "success", None
    elif state.get("exec_error"):
        status, error = "error", state["exec_error"]
    elif state.get("validation_error"):
        status, error = "error", f"could not produce valid SQL: {state['validation_error']}"
    else:
        status, error = "success", None

    final = {
        "question": state.get("question"),
        "status": status,
        "intent": intent,
        "error": error,
        "clarification": state.get("clarification"),
        "sql": state.get("sql", ""),
        "summary": state.get("summary")
        or state.get("router", {}).get("result")
        or state.get("clarification")
        or "",
        "columns": state.get("columns", []),
        "rows": state.get("rows", []),
        "row_count": state.get("row_count", 0),
        "truncated": state.get("truncated", False),
        "chart_type": state.get("chart_type", "table"),
        "chart_spec": state.get("chart_spec", {"type": "table", "title": "Results"}),
        "model": state.get("model"),
        "retries": state.get("retry_count", 0),
        "cost_usd": round(state.get("cost_usd", 0.0), 6),
        "llm_seconds": round(state.get("llm_seconds", 0.0), 4),
        "trace": state.get("trace", []),
    }
    return {"status": status, "error": error, "final": final}


def build_graph():
    """Compile and return the LangGraph app."""
    g = StateGraph(AgentState)

    g.add_node("router", router_node)
    g.add_node("schema", schema_node)
    g.add_node("sql_generation", sql_generator_node)
    g.add_node("validate", validator_node)
    g.add_node("repair", repair_node)
    g.add_node("execute", execute_node)
    g.add_node("summarize", summarizer_node)
    g.add_node("visualize", visualizer_node)
    g.add_node("aggregate", aggregate_node)

    g.add_edge(START, "router")
    g.add_conditional_edges("router", route_after_router,
                            {"schema": "schema", "aggregate": "aggregate"})
    g.add_edge("schema", "sql_generation")
    g.add_edge("sql_generation", "validate")
    g.add_conditional_edges("validate", route_after_validation,
                            {"execute": "execute", "repair": "repair", "aggregate": "aggregate"})
    g.add_edge("repair", "validate")
    # Parallel fan-out: both nodes read the result set; they join at aggregate.
    g.add_edge("execute", "summarize")
    g.add_edge("execute", "visualize")
    g.add_edge("summarize", "aggregate")
    g.add_edge("visualize", "aggregate")
    g.add_edge("aggregate", END)

    return g.compile()


_APP = None


def get_app():
    global _APP
    if _APP is None:
        _APP = build_graph()
    return _APP


def answer_question(question: str, model: str | None = None, max_retries: int = 2) -> dict[str, Any]:
    """Run the full pipeline for one question and return the final payload (with wall-clock)."""
    model = MODEL_REGISTRY.get(model, model) or DEFAULT_MODEL
    t0 = time.perf_counter()
    out = get_app().invoke(
        {"question": question, "model": model, "max_retries": max_retries, "retry_count": 0}
    )
    final = out.get("final", {})
    final["wall_clock_s"] = round(time.perf_counter() - t0, 4)
    return final
