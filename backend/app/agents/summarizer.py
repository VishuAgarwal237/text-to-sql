"""Summarizer node: turn the result rows into a concise plain-English answer.

Runs in parallel with the Visualizer (both only need the executed result set).
"""

from __future__ import annotations

import json
from typing import Any

from app.agents._common import run_llm_step
from app.prompts import load_prompt
from app.state import AgentState


def summarizer_node(state: AgentState) -> dict[str, Any]:
    if state.get("exec_error"):
        return {"summary": f"The query could not be executed: {state['exec_error']}"}

    rows = state.get("rows", [])
    system = load_prompt("summarizer")
    user = (
        f"QUESTION: {state['question']}\n\n"
        f"SQL (context only): {state.get('sql', '')}\n\n"
        f"COLUMNS: {json.dumps(state.get('columns', []))}\n"
        f"ROW_COUNT: {state.get('row_count', 0)} (truncated={state.get('truncated', False)})\n"
        f"ROWS (up to 50): {json.dumps(rows[:50], default=str)}\n\n"
        "Write the 1-3 sentence answer."
    )
    res, acct = run_llm_step("summarizer", system, user, state["model"], max_tokens=400)
    summary = (res.data or {}).get("summary") or (res.data or {}).get("result") or ""
    if not summary and not res.error:
        summary = "Query executed successfully."
    return {"summary": summary, **acct}
