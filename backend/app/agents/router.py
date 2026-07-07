"""Router / Intent node: classify the request and keep non-SQL traffic out of the pipeline."""

from __future__ import annotations

from typing import Any

from app.agents._common import run_llm_step
from app.prompts import load_prompt
from app.state import AgentState


def router_node(state: AgentState) -> dict[str, Any]:
    system = load_prompt("router")
    user = state["question"]
    res, acct = run_llm_step("router", system, user, state["model"], max_tokens=800)

    # Surface a provider/model failure (auth, quota/billing, timeout, bad JSON) as a clear
    # error rather than a misleading "clarification needed" — routes straight to aggregate.
    if res.error:
        return {
            "router": {"error": res.error},
            "intent": "unsupported",
            "clarification": None,
            "status": "error",
            "error": f"model error: {res.error}",
            **acct,
        }

    data = res.data or {}
    intent = data.get("intent", "analytical_sql")
    clarification = data.get("clarification")

    update: dict[str, Any] = {
        "router": data,
        "intent": intent,
        "clarification": clarification,
        **acct,
    }
    # Short-circuit statuses; the graph routes non-analytical intents straight to aggregate.
    if intent == "clarification_needed":
        update["status"] = "pending_user_input"
    elif intent in {"meta", "unsupported"}:
        update["status"] = "success"
    return update


def route_after_router(state: AgentState) -> str:
    """Conditional edge: only analytical questions enter the SQL path."""
    return "schema" if state.get("intent") == "analytical_sql" else "aggregate"
