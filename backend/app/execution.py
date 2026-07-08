"""Hardened query execution.

`db.run_query` enforces *read-only*. That is necessary but not sufficient on a large warehouse:
a read-only query can still be catastrophically expensive (an accidental cross join over billions
of rows, or a full scan with no LIMIT). This module adds the cost/blast-radius guards:

  - **LIMIT injection** — if the query has no outer LIMIT, one is added (via sqlglot AST, not
    string hacking) so a result set can never be unbounded.
  - **Cost pre-check** — `EXPLAIN QUERY PLAN` is inspected for full-table SCANs and cartesian
    joins; queries whose plan looks unbounded are rejected before execution.
  - **Statement timeout** — a watchdog thread calls `sqlite3.Connection.interrupt()` after
    `timeout_ms`, so a pathological query is killed instead of hanging the worker.
  - **Row cap** — results are truncated at `max_rows` (inherited from the read-only core).

The SQLite specifics (EXPLAIN QUERY PLAN, `interrupt`) are the reference implementation; on
Postgres/Snowflake the same three guards map to `EXPLAIN (FORMAT JSON)` cost, `statement_timeout`,
and a `LIMIT`/`row_limit` — same contract, different driver.
"""

from __future__ import annotations

import sqlite3
import threading
from typing import Any

import sqlglot
from sqlglot import exp

from app import db

DEFAULT_TIMEOUT_MS = 5000
DEFAULT_MAX_ROWS = 1000
# Reject a plan with more than this many independent full scans (proxy for a cartesian blow-up).
MAX_FULL_SCANS = 4


class QueryCostError(RuntimeError):
    """Raised when a query's estimated plan exceeds the allowed blast radius."""


class QueryTimeout(RuntimeError):
    """Raised when a query is interrupted for exceeding the statement timeout."""


def ensure_limit(sql: str, max_rows: int) -> str:
    """Return `sql` with an outer LIMIT of at most `max_rows`. Uses the AST so we don't break
    on subquery LIMITs, comments, or trailing whitespace. Non-SELECT is caller's problem."""
    try:
        tree = sqlglot.parse_one(sql, read="sqlite")
    except Exception:
        return sql  # let the read-only guard / EXPLAIN reject it downstream
    if not isinstance(tree, (exp.Select, exp.Union, exp.Subquery)):
        return sql
    existing = tree.args.get("limit")
    if existing is None:
        return tree.limit(max_rows).sql(dialect="sqlite")
    # Tighten an existing over-large LIMIT down to the cap.
    try:
        if int(existing.expression.name) > max_rows:
            return tree.limit(max_rows).sql(dialect="sqlite")
    except (AttributeError, ValueError):
        pass
    return tree.sql(dialect="sqlite")


def check_cost(sql: str) -> dict[str, Any]:
    """Inspect EXPLAIN QUERY PLAN. Rejects queries whose plan shows too many full scans (a proxy
    for missing indexes / cartesian joins). Returns the plan summary for the trace."""
    cleaned = db.assert_read_only(sql)
    conn = db.connect_ro()
    try:
        rows = conn.execute(f"EXPLAIN QUERY PLAN {cleaned}").fetchall()
    finally:
        conn.close()
    details = [r["detail"] if "detail" in r.keys() else str(tuple(r)) for r in rows]
    full_scans = sum(1 for d in details if d.upper().startswith("SCAN"))
    if full_scans > MAX_FULL_SCANS:
        raise QueryCostError(
            f"Query plan has {full_scans} full scans (limit {MAX_FULL_SCANS}); "
            f"likely a missing filter/index or cartesian join. Plan: {details}"
        )
    return {"full_scans": full_scans, "plan": details}


def run_guarded(
    sql: str,
    max_rows: int = DEFAULT_MAX_ROWS,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> dict[str, Any]:
    """Execute a read-only query under all guards: LIMIT-injected, cost-checked, time-boxed,
    row-capped. Returns the same shape as `db.run_query` plus a `guards` trace."""
    # Probe one past the cap so we can distinguish "exactly max_rows" from "truncated". Injecting
    # LIMIT max_rows would make truncation undetectable — the DB would return exactly max_rows.
    bounded = ensure_limit(sql, max_rows + 1)
    cost = check_cost(bounded)

    cleaned = db.assert_read_only(bounded)
    conn = db.connect_ro()
    timed_out = threading.Event()

    def _watchdog():
        if not _done.wait(timeout_ms / 1000):
            timed_out.set()
            conn.interrupt()  # thread-safe cancel of the running statement

    _done = threading.Event()
    timer = threading.Thread(target=_watchdog, daemon=True)
    timer.start()
    try:
        cur = conn.execute(cleaned)
        columns = [d[0] for d in cur.description] if cur.description else []
        fetched = cur.fetchmany(max_rows + 1)
        truncated = len(fetched) > max_rows
        rows = [dict(r) for r in fetched[:max_rows]]
    except sqlite3.OperationalError as e:
        if timed_out.is_set():
            raise QueryTimeout(f"Query exceeded {timeout_ms}ms and was interrupted.") from e
        raise
    finally:
        _done.set()
        conn.close()

    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
        "guards": {"executed_sql": cleaned, "limit_applied": max_rows, **cost},
    }
