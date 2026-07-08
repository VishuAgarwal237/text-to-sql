from app.schema.fk_graph import FKGraph


def test_bridges_disconnected_anchors(catalog):
    g = FKGraph.build(catalog)
    conn = g.connect(["Genre", "InvoiceLine"])
    # Track is the required bridge between Genre and InvoiceLine.
    assert conn["tables"] == ["Genre", "InvoiceLine", "Track"]
    assert conn["bridge_tables"] == ["Track"]
    assert conn["unconnected"] == []
    assert set(conn["join_clauses"]) == {
        "Track.GenreId = Genre.GenreId",
        "InvoiceLine.TrackId = Track.TrackId",
    }


def test_single_anchor_needs_no_joins(catalog):
    g = FKGraph.build(catalog)
    conn = g.connect(["Genre"])
    assert conn["tables"] == ["Genre"]
    assert conn["join_clauses"] == []


def test_flags_truly_unconnected(catalog):
    # Remove the Invoice→Customer relationship so Customer is isolated from the music path.
    cat = {**catalog, "relationships": [
        r for r in catalog["relationships"] if "Customer" not in r["from"]]}
    g = FKGraph.build(cat)
    conn = g.connect(["Genre", "Customer"])
    assert "Customer" in conn["unconnected"]
    # Isolated anchor is still kept so its columns aren't silently dropped.
    assert "Customer" in conn["tables"]


def test_ignores_unknown_tables(catalog):
    g = FKGraph.build(catalog)
    conn = g.connect(["Genre", "DoesNotExist"])
    assert conn["tables"] == ["Genre"]
