"""Execution agent: run the validated read-only SQL and return rows + columns.

Two backends, both enforcing the same read-only guard (app.db):
  - EXEC_BACKEND=mcp     -> spawn the read-only SQLite MCP server (app.mcp_server) over stdio
                           and call its `run_sql` tool (the architecture's MCP path).
  - EXEC_BACKEND=direct  -> call app.db.run_query in-process (default; fast + dependency-free,
                           used by the eval harness and tests).

Both return identical results because the MCP server is a thin wrapper over the same core.
"""

from __future__ import annotations

import json
import os

from app import db


def _run_direct(sql: str, max_rows: int) -> dict:
    return db.run_query(sql, max_rows=max_rows)


def _run_mcp(sql: str, max_rows: int) -> dict:
    """Execute via the MCP SQLite server over stdio (async client wrapped synchronously)."""
    import asyncio
    import sys
    from pathlib import Path

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    backend_dir = str(Path(__file__).resolve().parents[2])

    async def _call() -> dict:
        # Use the SAME interpreter (venv) and ensure `app` is importable in the subprocess.
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "app.mcp_server"],
            cwd=backend_dir,
            env={**os.environ, "PYTHONPATH": backend_dir},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                res = await session.call_tool("run_sql", {"sql": sql, "max_rows": max_rows})
                text = res.content[0].text  # tool returns a JSON string
                return json.loads(text)

    return asyncio.run(_call())


def execute(sql: str, max_rows: int = 1000) -> dict:
    """Run `sql` and return {'columns','rows','row_count','truncated'} or {'error','message'}."""
    backend = os.environ.get("EXEC_BACKEND", "direct").lower()
    try:
        if backend == "mcp":
            out = _run_mcp(sql, max_rows)
        else:
            out = _run_direct(sql, max_rows)
    except db.UnsafeSQLError as e:
        return {"error": "unsafe_sql", "message": str(e)}
    except Exception as e:
        return {"error": "execution_error", "message": str(e)}

    if isinstance(out, dict) and out.get("error"):
        return out
    return out


def execute_node(state: "dict") -> dict:
    """LangGraph node: execute the validated SQL and record rows/columns or an execution error."""
    out = execute(state.get("sql", ""))
    trace_entry = {"step": "execute", "backend": os.environ.get("EXEC_BACKEND", "direct")}
    if out.get("error"):
        trace_entry["error"] = out.get("message")
        return {
            "exec_error": out.get("message"),
            "columns": [], "rows": [], "row_count": 0, "truncated": False,
            "trace": [trace_entry],
        }
    trace_entry["row_count"] = out["row_count"]
    return {
        "columns": out["columns"],
        "rows": out["rows"],
        "row_count": out["row_count"],
        "truncated": out.get("truncated", False),
        "exec_error": None,
        "trace": [trace_entry],
    }
