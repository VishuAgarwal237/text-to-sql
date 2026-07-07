"""Visualizer node: decide the chart type (rules-first) and emit a render-ready spec.

Answers RTF Q8 ("who decides the viz"): a deterministic rules engine (app.viz) makes the pick,
the LLM acts only as a tie-breaker/override, and the concrete spec (x/y/series/title) is built
in code so the frontend always gets valid fields. Runs in parallel with the Summarizer.
"""

from __future__ import annotations

import json
from typing import Any

from app import viz
from app.agents._common import run_llm_step
from app.prompts import load_prompt
from app.state import AgentState


def visualizer_node(state: AgentState) -> dict[str, Any]:
    columns = state.get("columns", [])
    rows = state.get("rows", [])

    if state.get("exec_error") or not rows:
        spec = viz.build_spec("table", columns, rows, title="No results")
        return {"chart_type": "table", "chart_spec": spec}

    # 1) Deterministic rule-based recommendation.
    rule = viz.rule_based_chart(columns, rows)
    types = viz.infer_types(columns, rows)

    # 2) LLM tie-breaker / override.
    system = load_prompt("visualizer")
    user = (
        f"QUESTION: {state['question']}\n"
        f"COLUMNS_WITH_TYPES: {json.dumps(types)}\n"
        f"ROW_COUNT: {len(rows)}\n"
        f"SAMPLE_ROWS: {json.dumps(rows[:5], default=str)}\n"
        f'rule_based: "{rule["chart_type"]}"  (reason: {rule["reason"]})\n\n'
        "Confirm or override the chart type."
    )
    res, acct = run_llm_step("visualizer", system, user, state["model"], max_tokens=500)
    chosen = (res.data or {}).get("chart_type")
    if chosen not in viz.CHART_TYPES:
        chosen = rule["chart_type"]

    # 3) Build the concrete spec in code (never trust the model for x/y roles).
    title = (res.data or {}).get("chart_spec", {}).get("title") or "Query Results"
    spec = viz.build_spec(chosen, columns, rows, title=title)
    return {"chart_type": chosen, "chart_spec": spec, **acct}
