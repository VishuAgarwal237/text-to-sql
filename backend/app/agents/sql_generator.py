"""SQL Generation node: compose one read-only SQLite query from the hydrated context + few-shot."""

from __future__ import annotations

from typing import Any

from app.agents._common import run_llm_step
from app.prompts import load_prompt
from app.state import AgentState

# Curated few-shot examples spanning the common query shapes (aggregation+joins, filtering,
# date filtering, sorting). These teach dialect idioms (strftime, ||) and the InvoiceLine-vs-
# Invoice.Total revenue distinction without leaking the eval's exact questions.
FEW_SHOT = """
EXAMPLES (question -> SQL):

Q: What are the top 3 genres by number of tracks?
SQL: SELECT g.Name, COUNT(t.TrackId) AS TrackCount FROM Genre g JOIN Track t ON g.GenreId = t.GenreId GROUP BY g.GenreId, g.Name ORDER BY TrackCount DESC LIMIT 3

Q: How much revenue did we make from Jazz tracks?
SQL: SELECT SUM(il.UnitPrice * il.Quantity) AS Revenue FROM Genre g JOIN Track t ON g.GenreId = t.GenreId JOIN InvoiceLine il ON t.TrackId = il.TrackId WHERE g.Name = 'Jazz'

Q: List customers from Canada with their emails.
SQL: SELECT FirstName, LastName, Email FROM Customer WHERE Country = 'Canada'

Q: What was total revenue per year?
SQL: SELECT strftime('%Y', InvoiceDate) AS Year, SUM(Total) AS Revenue FROM Invoice GROUP BY Year ORDER BY Year
""".strip()


def sql_generator_node(state: AgentState) -> dict[str, Any]:
    system = load_prompt("sql_generation")
    user = (
        f"QUESTION: {state['question']}\n\n"
        f"SCHEMA CONTEXT:\n{state.get('schema_context', '')}\n\n"
        f"{FEW_SHOT}\n\n"
        "Now write the single read-only SQLite query for the QUESTION."
    )
    res, acct = run_llm_step("sql_generation", system, user, state["model"], max_tokens=1200)
    data = res.data or {}
    sql = (data.get("sql") or "").strip()

    update: dict[str, Any] = {
        "sql": sql,
        "sql_history": [{"stage": "generate", "sql": sql, "error": res.error}],
        **acct,
    }
    if not sql:
        update["validation_error"] = res.error or "empty SQL from generator"
    return update
