"""Read-only SQLite MCP server for the Chinook database.

Exposes the database to the execution agent over the Model Context Protocol (stdio). Every
tool is backed by the shared read-only core in app.db, so writes/DDL/PRAGMA/stacked statements
are rejected here exactly as everywhere else — the MCP boundary adds process isolation on top
of the in-code guard.

Tools:
  - run_sql(sql, max_rows): execute a validated read-only SELECT, return columns + rows.
  - describe_schema(): return the live schema (tables, columns, foreign keys).

Run standalone (stdio transport):
    python -m app.mcp_server

The execution node launches this as a subprocess and speaks MCP to it (see app/agents/executor.py).
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from app import db

mcp = FastMCP("chinook-readonly")


@mcp.tool()
def run_sql(sql: str, max_rows: int = 1000) -> str:
    """Execute a READ-ONLY SQLite SELECT/CTE against the Chinook database.

    Returns a JSON string: {"columns": [...], "rows": [...], "row_count": N, "truncated": bool}.
    Rejects any non-read-only statement (INSERT/UPDATE/DELETE/DDL/PRAGMA/multiple statements)
    with an error message rather than executing it.
    """
    try:
        result = db.run_query(sql, max_rows=max_rows)
        return json.dumps(result, default=str)
    except db.UnsafeSQLError as e:
        return json.dumps({"error": "unsafe_sql", "message": str(e)})
    except Exception as e:  # sqlite3 errors, etc.
        return json.dumps({"error": "execution_error", "message": str(e)})


@mcp.tool()
def describe_schema() -> str:
    """Return the live Chinook schema as JSON: tables -> columns (name/type/pk) + foreign keys."""
    return json.dumps(db.get_schema(), default=str)


if __name__ == "__main__":
    mcp.run()
