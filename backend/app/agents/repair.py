"""Repair node: given the failing SQL + exact error, produce a corrected read-only query.

Increments retry_count and loops back to the validator (the self-correcting loop). Capped by
max_retries in the validator's routing.
"""

from __future__ import annotations

from typing import Any

from app.agents._common import run_llm_step
from app.prompts import load_prompt
from app.state import AgentState


def repair_node(state: AgentState) -> dict[str, Any]:
    system = load_prompt("repair")
    retry = state.get("retry_count", 0) + 1
    user = (
        f"QUESTION: {state['question']}\n\n"
        f"SCHEMA CONTEXT:\n{state.get('schema_context', '')}\n\n"
        f'previous_sql: "{state.get("sql", "")}"\n'
        f"validator_error: {state.get('validation_error')}\n"
        f"retry: {retry} of {state.get('max_retries', 2)}\n\n"
        "Return a corrected single read-only SQLite query."
    )
    res, acct = run_llm_step("repair", system, user, state["model"], max_tokens=1200)
    data = res.data or {}
    fixed = (data.get("sql") or "").strip()

    return {
        "sql": fixed or state.get("sql", ""),
        "retry_count": retry,
        "sql_history": [{"stage": "repair", "sql": fixed,
                         "fix": data.get("fix_explanation"), "error": res.error}],
        **acct,
    }
