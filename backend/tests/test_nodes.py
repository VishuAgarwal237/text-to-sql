"""Full pipeline via the framework-agnostic runner (no langgraph needed)."""

from app import nodes
from tests.conftest import FakeLLM, j

_GOOD_SQL = ("SELECT g.Name, SUM(il.UnitPrice*il.Quantity) AS TotalSales "
             "FROM Genre g JOIN Track t ON g.GenreId=t.GenreId "
             "JOIN InvoiceLine il ON t.TrackId=il.TrackId GROUP BY g.Name ORDER BY TotalSales DESC")

_HYDRATION = j({
    "status": "success", "selected_tables": ["Genre", "InvoiceLine"],
    "selected_columns": {"Genre": ["Name"], "InvoiceLine": ["UnitPrice", "Quantity"]},
    "resolved_concepts": [], "dialect_notes": [],
})
_PRESENTATION = j({"summary": "Rock leads with $2.97.", "chart_type": "bar",
                   "chart_spec": {"type": "bar", "x": "Name", "y": ["TotalSales"]}})


def test_analytical_happy_path(chinook_db, make_resources):
    llm = FakeLLM({
        "router": j({"intent": "analytical_sql", "entities": {"metrics": ["revenue"]}, "result": ""}),
        "hydration": _HYDRATION,
        "sql": j({"sql": _GOOD_SQL, "assumptions": ["ranked by total revenue"]}),
        "presentation": _PRESENTATION,
    })
    state = nodes.run_pipeline("top selling genres by revenue", make_resources(llm))
    answer = state["answer"]
    assert answer["kind"] == "analytical_sql"
    assert answer["rows"][0]["Name"] == "Rock"  # Rock 2.97 > Latin 1.99
    assert answer["summary"] == "Rock leads with $2.97."
    assert answer["chart_type"] == "bar"
    assert state["trace"] == ["router", "hydrate", "generate_sql", "validate", "execute",
                              "present", "aggregate"]
    assert "repair" not in state["trace"]


def test_meta_short_circuits(chinook_db, make_resources):
    llm = FakeLLM({"router": j({"intent": "meta", "entities": {}, "result": "Hi! Ask me about sales."})})
    state = nodes.run_pipeline("hello", make_resources(llm))
    assert state["answer"] == {"kind": "meta", "message": "Hi! Ask me about sales."}
    assert llm.calls == ["router"]  # never entered the SQL path


def test_repair_loop_recovers(chinook_db, make_resources):
    llm = FakeLLM({
        "router": j({"intent": "analytical_sql", "entities": {}, "result": ""}),
        "hydration": _HYDRATION,
        "sql": j({"sql": "SELECT Nope FROM Genre", "assumptions": []}),   # invalid column
        "repair": j({"sql": "SELECT Name FROM Genre ORDER BY Name", "fix_explanation": "fixed col"}),
        "presentation": _PRESENTATION,
    })
    state = nodes.run_pipeline("list genres", make_resources(llm))
    assert "repair" in state["trace"]
    assert state["retries"] == 1
    assert state["answer"]["sql"] == "SELECT Name FROM Genre ORDER BY Name"
    assert state["answer"]["rows"][0]["Name"] == "Latin"


def test_repair_gives_up_after_max_retries(chinook_db, make_resources):
    llm = FakeLLM({
        "router": j({"intent": "analytical_sql", "entities": {}, "result": ""}),
        "hydration": _HYDRATION,
        "sql": j({"sql": "SELECT Nope FROM Genre", "assumptions": []}),
        # repair keeps returning something invalid → loop must terminate, not spin.
        "repair": [j({"sql": "SELECT StillNope FROM Genre"}),
                   j({"sql": "SELECT AlsoNope FROM Genre"})],
        "presentation": _PRESENTATION,
    })
    state = nodes.run_pipeline("list genres", make_resources(llm, max_retries=2))
    assert state["retries"] == 2
    assert state.get("error")  # surfaced the failure instead of looping forever
    assert state["trace"].count("repair") == 2
