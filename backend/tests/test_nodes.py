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


def test_polish_sql_orders_grouped_aggregates_by_metric_desc():
    sql = "SELECT Country, COUNT(*) AS CustomerCount FROM Customer GROUP BY Country"

    assert nodes.polish_sql(sql, "How many customers does each country have?") == (
        "SELECT Country, COUNT(*) AS CustomerCount FROM Customer "
        "GROUP BY Country ORDER BY CustomerCount DESC, Country DESC"
    )


def test_polish_sql_preserves_duplicate_playlist_names_and_empty_playlists():
    sql = (
        "SELECT p.Name, COUNT(pt.TrackId) AS TrackCount FROM Playlist p "
        "JOIN PlaylistTrack pt ON p.PlaylistId = pt.PlaylistId GROUP BY p.Name"
    )

    assert nodes.polish_sql(sql, "How many tracks are there in each playlist?") == (
        "SELECT p.Name, COUNT(pt.TrackId) AS TrackCount FROM Playlist p "
        "LEFT JOIN PlaylistTrack pt ON p.PlaylistId = pt.PlaylistId "
        "GROUP BY p.PlaylistId, p.Name ORDER BY TrackCount DESC, p.Name DESC"
    )


def test_polish_sql_limits_singular_superlative():
    sql = (
        "SELECT mt.Name, COUNT(t.TrackId) AS TrackCount FROM MediaType mt "
        "JOIN Track t ON mt.MediaTypeId = t.MediaTypeId GROUP BY mt.Name "
        "ORDER BY TrackCount DESC"
    )

    assert nodes.polish_sql(sql, "What is the most popular media type based on number of tracks?") == (
        "SELECT mt.Name, COUNT(t.TrackId) AS TrackCount FROM MediaType mt "
        "JOIN Track t ON mt.MediaTypeId = t.MediaTypeId GROUP BY mt.Name "
        "ORDER BY TrackCount DESC LIMIT 1"
    )


def test_polish_sql_preserves_customer_name_columns_for_name_and_email_request():
    sql = (
        "SELECT Customer.FirstName || ' ' || Customer.LastName AS Name, Customer.Email "
        "FROM Customer WHERE Customer.Country = 'Brazil'"
    )

    assert nodes.polish_sql(sql, "What are the names and email addresses of customers from Brazil?") == (
        "SELECT Customer.FirstName, Customer.LastName, Customer.Email "
        "FROM Customer WHERE Customer.Country = 'Brazil'"
    )


def test_polish_sql_keeps_temporal_series_chronological():
    sql = (
        "SELECT strftime('%Y-%m', InvoiceDate) AS Month, SUM(Total) AS Revenue "
        "FROM Invoice GROUP BY Month ORDER BY Month"
    )

    assert nodes.polish_sql(sql, "Show monthly sales revenue.") == sql
