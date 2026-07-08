"""Read-only SQLite access core.

This is the single execution primitive for the whole system. It is reused by:
  - the MCP SQLite server (app/mcp_server.py) that the execution agent calls,
  - the eval harness (eval/*) which runs candidate SQL and ground-truth SQL directly,
  - the validation/repair node which dry-runs EXPLAIN.

Every entry point is guarded to be strictly read-only. The connection is opened in
SQLite immutable/read-only mode AND every statement is screened, so a write can never
reach the database even if the model is prompt-injected into emitting one.
"""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path
from typing import Any

# Resolve the DB path from env, defaulting to the repo's data/ copy. In Docker this is
# a read-only bind mount; locally it points at data/Chinook.db.
DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "Chinook.db"
DB_PATH = Path(os.environ.get("CHINOOK_DB_PATH", str(DEFAULT_DB_PATH)))

# Statement keywords that mutate data or schema, or otherwise escape the read-only intent.
# Screened case-insensitively as whole words against the (comment-stripped) SQL.
_FORBIDDEN = {
    "insert", "update", "delete", "drop", "alter", "create", "replace",
    "truncate", "attach", "detach", "reindex", "vacuum", "pragma",
    "grant", "revoke", "commit", "begin", "rollback", "savepoint",
}


class UnsafeSQLError(ValueError):
    """Raised when a statement is not a single read-only SELECT/CTE."""


def _strip_sql_comments(sql: str) -> str:
    """Remove -- line comments and /* */ block comments so keyword screening can't be
    bypassed by hiding a write inside a comment-adjacent construct."""
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return sql


def assert_read_only(sql: str) -> str:
    """Validate that `sql` is a single read-only statement. Returns the cleaned SQL.

    Rules:
      - exactly one statement (no stacked queries separated by `;`),
      - must start with SELECT or WITH (CTE),
      - must contain no forbidden (mutating) keyword.
    """
    if not sql or not sql.strip():
        raise UnsafeSQLError("Empty SQL.")

    cleaned = _strip_sql_comments(sql).strip().rstrip(";").strip()

    # Reject stacked statements: any remaining semicolon means more than one statement.
    if ";" in cleaned:
        raise UnsafeSQLError("Multiple statements are not allowed; submit a single SELECT.")

    lowered = cleaned.lower()
    if not (lowered.startswith("select") or lowered.startswith("with")):
        raise UnsafeSQLError("Only read-only SELECT (or WITH ... SELECT) queries are allowed.")

    tokens = set(re.findall(r"[a-z_]+", lowered))
    hit = tokens & _FORBIDDEN
    if hit:
        raise UnsafeSQLError(f"Forbidden keyword(s) in query: {', '.join(sorted(hit))}")

    return cleaned


def _connect() -> sqlite3.Connection:
    """Open the database read-only via URI mode so the OS/driver also blocks writes."""
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Chinook database not found at {DB_PATH}. Set CHINOOK_DB_PATH or run setup."
        )
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def run_query(sql: str, max_rows: int = 1000) -> dict[str, Any]:
    """Execute a validated read-only query and return a structured result.

    Returns {"columns": [...], "rows": [ {col: val}, ... ], "row_count": int, "truncated": bool}.
    Raises UnsafeSQLError for non-read-only SQL and sqlite3.Error for execution errors.
    """
    cleaned = assert_read_only(sql)
    conn = _connect()
    try:
        cur = conn.execute(cleaned)
        columns = [d[0] for d in cur.description] if cur.description else []
        fetched = cur.fetchmany(max_rows + 1)
        truncated = len(fetched) > max_rows
        rows = [dict(r) for r in fetched[:max_rows]]
        return {
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "truncated": truncated,
        }
    finally:
        conn.close()


def explain(sql: str) -> None:
    """Dry-run a query via EXPLAIN to validate it parses and binds without executing it.

    Raises UnsafeSQLError or sqlite3.Error if invalid; returns None on success.
    """
    cleaned = assert_read_only(sql)
    conn = _connect()
    try:
        conn.execute(f"EXPLAIN {cleaned}").fetchone()
    finally:
        conn.close()


def get_schema() -> dict[str, Any]:
    """Introspect live schema: tables, columns (name/type/nullable/pk), and foreign keys.

    Used by the metadata generator (offline) and the schema-hydration agent (runtime) as
    ground truth that the LLM-authored catalog is layered on top of.
    """
    conn = _connect()
    try:
        tables = [
            r["name"]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        schema: dict[str, Any] = {}
        for t in tables:
            cols = [
                {
                    "name": c["name"],
                    "type": c["type"],
                    "not_null": bool(c["notnull"]),
                    "primary_key": bool(c["pk"]),
                }
                for c in conn.execute(f'PRAGMA table_info("{t}")')
            ]
            fks = [
                {
                    "column": f["from"],
                    "references_table": f["table"],
                    "references_column": f["to"],
                }
                for f in conn.execute(f'PRAGMA foreign_key_list("{t}")')
            ]
            schema[t] = {"columns": cols, "foreign_keys": fks}
        return schema
    finally:
        conn.close()


def connect_ro() -> sqlite3.Connection:
    """Public read-only connection factory. Exposed for the execution guard, which needs the
    live connection to install a timeout watchdog and read EXPLAIN QUERY PLAN. Callers are
    responsible for closing it and MUST only run SQL that passed `assert_read_only`."""
    return _connect()


# Sampling is capped by scanning only the first `scan_limit` rows rather than the whole table,
# so it stays cheap on large tables (approximate, not exact — sufficient for the value index).
def sample_column_values(
    table: str, column: str, limit: int = 20, scan_limit: int = 10000
) -> list[tuple[Any, int]]:
    """Return up to `limit` most-frequent non-null values of a column as (value, count),
    scanning at most `scan_limit` rows. Used by the value/entity index and metadata generator."""
    conn = _connect()
    try:
        cur = conn.execute(
            f'SELECT v, COUNT(*) AS c FROM '
            f'(SELECT "{column}" AS v FROM "{table}" WHERE "{column}" IS NOT NULL LIMIT ?) '
            f'GROUP BY v ORDER BY c DESC LIMIT ?',
            (scan_limit, limit),
        )
        return [(r["v"], r["c"]) for r in cur]
    finally:
        conn.close()


def approx_distinct_count(table: str, column: str, scan_limit: int = 10000) -> int:
    """Approximate distinct-value count of a column over the first `scan_limit` rows.
    Lets the value index skip high-cardinality columns (ids, free text) it shouldn't index."""
    conn = _connect()
    try:
        row = conn.execute(
            f'SELECT COUNT(DISTINCT v) AS n FROM '
            f'(SELECT "{column}" AS v FROM "{table}" WHERE "{column}" IS NOT NULL LIMIT ?)',
            (scan_limit,),
        ).fetchone()
        return int(row["n"]) if row else 0
    finally:
        conn.close()


if __name__ == "__main__":
    # Smoke test: print table names and prove the read-only guard blocks a write.
    print("Tables:", list(get_schema().keys()))
    try:
        run_query("DELETE FROM Artist")
    except UnsafeSQLError as e:
        print("Guard OK — blocked write:", e)
