"""Shared LangGraph state for the text-to-SQL pipeline.

A single TypedDict flows through every node. Nodes return partial updates. Three fields use
additive reducers so the two parallel nodes (summarizer ‖ visualizer) can both append to the
trace and both contribute cost/latency without a concurrent-write conflict.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class AgentState(TypedDict, total=False):
    # --- inputs ---
    question: str
    model: str            # LiteLLM model id (or registry key) to run this request under
    max_retries: int

    # --- router ---
    intent: str           # analytical_sql | clarification_needed | meta | unsupported
    router: dict[str, Any]
    clarification: str | None

    # --- schema hydration ---
    schema_context: str
    hydration: dict[str, Any]

    # --- sql generation + validation/repair loop ---
    sql: str
    validation_error: str | None
    retry_count: int
    sql_history: Annotated[list[dict[str, Any]], operator.add]

    # --- execution ---
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    exec_error: str | None

    # --- parallel: summarize ‖ visualize ---
    summary: str
    chart_type: str
    chart_spec: dict[str, Any]

    # --- outputs / accounting (additive so parallel nodes merge cleanly) ---
    status: str           # success | error | pending_user_input
    error: str | None
    trace: Annotated[list[dict[str, Any]], operator.add]
    cost_usd: Annotated[float, operator.add]
    llm_seconds: Annotated[float, operator.add]
    final: dict[str, Any]
