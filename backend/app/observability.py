"""Braintrust observability hooks.

This module is deliberately optional at import time: the core app and unit tests keep running when
Braintrust is not installed or `BRAINTRUST_API_KEY` is not set. When enabled, it logs one root span
per user question with the final answer plus compact pipeline metadata.
"""

from __future__ import annotations

import os
from contextlib import nullcontext
from typing import Any

from app import nodes
from app.state import AgentState, Resources

DEFAULT_PROJECT = "text-to-sql"


def enabled() -> bool:
    """True when the environment is configured to send Braintrust logs."""
    return bool(os.environ.get("BRAINTRUST_API_KEY"))


def _braintrust():
    try:
        import braintrust
    except ImportError:
        return None
    return braintrust


def init(project: str = DEFAULT_PROJECT) -> bool:
    """Initialize Braintrust logging if available and configured.

    Returns whether logging is active. This lets CLI/API entrypoints surface a clear startup state
    without making Braintrust a hard dependency of the text-to-SQL runtime.
    """
    if not enabled():
        return False
    bt = _braintrust()
    if bt is None:
        return False
    bt.init_logger(project=project)
    if hasattr(bt, "auto_instrument"):
        bt.auto_instrument()
    return True


def _span_context(project: str, name: str):
    if not init(project):
        return nullcontext(None)
    bt = _braintrust()
    if bt is None:
        return nullcontext(None)
    try:
        return bt.start_span(name=name)
    except TypeError:
        return bt.start_span()


def _metadata(state: AgentState) -> dict[str, Any]:
    answer = state.get("answer", {})
    return {
        "trace": state.get("trace", []),
        "intent": state.get("intent"),
        "sql": answer.get("sql"),
        "row_count": answer.get("row_count"),
        "truncated": answer.get("truncated"),
        "chart_type": answer.get("chart_type"),
        "error": answer.get("error") or state.get("error") or state.get("validation_error"),
    }


def run_observed_pipeline(
    question: str,
    res: Resources,
    *,
    project: str = DEFAULT_PROJECT,
) -> AgentState:
    """Run the existing pipeline and log input/output/metadata to Braintrust when configured."""
    with _span_context(project, "text_to_sql_pipeline") as span:
        state = nodes.run_pipeline(question, res)
        if span is not None:
            span.log(input=question, output=state.get("answer", {}), metadata=_metadata(state))
        return state
