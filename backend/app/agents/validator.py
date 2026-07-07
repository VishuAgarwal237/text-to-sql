"""Validation node (deterministic) + repair routing.

Three gates, cheapest first:
  1. read-only guard (app.db.assert_read_only): reject writes/DDL/PRAGMA/stacked statements,
  2. static parse via sqlglot (SQLite dialect),
  3. EXPLAIN dry-run against a read-only connection (binds columns/tables without executing).

On success -> execute. On failure -> repair (until max_retries) -> aggregate (as error).
This is a pure code node; the LLM only re-enters via the Repair node it routes to.
"""

from __future__ import annotations

from typing import Any

import sqlglot

from app import db
from app.state import AgentState


def _validate(sql: str) -> str | None:
    """Return an error string if invalid, else None."""
    if not sql or not sql.strip():
        return "empty SQL"
    try:
        db.assert_read_only(sql)
    except db.UnsafeSQLError as e:
        return f"read-only violation: {e}"
    try:
        sqlglot.parse_one(sql, read="sqlite")
    except Exception as e:
        return f"parse error: {e}"
    try:
        db.explain(sql)
    except Exception as e:
        return f"EXPLAIN failed: {e}"
    return None


def validator_node(state: AgentState) -> dict[str, Any]:
    err = _validate(state.get("sql", ""))
    trace_entry = {"step": "validate", "ok": err is None, "error": err}
    return {"validation_error": err, "trace": [trace_entry]}


def route_after_validation(state: AgentState) -> str:
    """execute if valid; repair if we still have retries; else aggregate as an error."""
    if not state.get("validation_error"):
        return "execute"
    if state.get("retry_count", 0) < state.get("max_retries", 2):
        return "repair"
    return "aggregate"
