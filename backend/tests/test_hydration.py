"""The hydration subgraph end-to-end: retrieval → value-linking → budget → LLM chooses →
FK-graph joins. The LLM is faked to a fixed table choice; everything else is real."""

import json

from app.agents import hydration
from tests.conftest import j


def _fake_hydration_llm(system, user):
    # The LLM chooses Genre + InvoiceLine; the FK graph must supply the Track bridge.
    assert "Schema Hydration" in system
    # The bundle it reads should contain candidate metadata, not raw DDL.
    assert "TABLE Genre" in user
    return j({
        "status": "success",
        "selected_tables": ["Genre", "InvoiceLine"],
        "selected_columns": {"Genre": ["Name"], "InvoiceLine": ["UnitPrice", "Quantity"]},
        "resolved_concepts": [
            {"phrase": "revenue", "resolution": "SUM(InvoiceLine.UnitPrice*InvoiceLine.Quantity)"}],
        "resolved_filters": [
            {"phrase": "in Germany", "column": "Customer.Country",
             "predicate": "Customer.Country = 'Germany'"}],
        "dialect_notes": ["strftime for dates"],
    })


def test_hydrate_bridges_and_links(embed_index, value_index, fk_graph, catalog):
    out = hydration.hydrate(
        "top selling genres by revenue in Germany", {"metrics": ["revenue"]},
        catalog, embed_index, value_index, fk_graph, complete_fn=_fake_hydration_llm,
    )
    # FK graph supplied the bridge table the LLM didn't ask for.
    assert "Track" in out["selected_tables"]
    assert out["bridge_tables"] == ["Track"]
    assert set(out["join_clauses"]) == {
        "Track.GenreId = Genre.GenreId", "InvoiceLine.TrackId = Track.TrackId"}
    # Value linking surfaced Germany → Customer.Country as a hint.
    assert "Germany" in out["value_hints"]
    assert out["value_hints"]["Germany"][0]["column"] == "Country"
    # Assembled context carries joins + resolved concepts downstream.
    assert "JOINS:" in out["schema_context"]
    assert "RESOLVED CONCEPTS:" in out["schema_context"]
    assert out["trace"]["candidates"]  # retrieval produced candidates


def test_hydrate_trace_reports_budget(embed_index, value_index, fk_graph, catalog):
    out = hydration.hydrate(
        "revenue by genre", {}, catalog, embed_index, value_index, fk_graph,
        complete_fn=_fake_hydration_llm, budget_tokens=10_000,
    )
    assert out["trace"]["included_tables"]
    assert isinstance(out["trace"]["tokens_used"], int)
