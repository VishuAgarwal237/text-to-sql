from app.retrieval.value_index import ValueIndex


def test_links_literal_to_column(value_index):
    hits = value_index.query("total sales in Germany")
    assert "Germany" in hits
    cols = {(h["table"], h["column"]) for h in hits["Germany"]}
    assert ("Customer", "Country") in cols


def test_candidate_tables_from_values(value_index):
    assert "Customer" in value_index.candidate_tables("customers in Germany")
    assert "Genre" in value_index.candidate_tables("how many Rock tracks")


def test_skips_numeric_and_id_columns(value_index):
    # Integer id/type columns must not be indexed as entities.
    flat = [tuple(pair[:2]) for hits in value_index.inverted.values() for pair in hits]
    assert ("Genre", "GenreId") not in flat
    assert ("Invoice", "Total") not in flat  # NUMERIC skipped by type


def test_persistence_round_trip(value_index, tmp_path):
    p = tmp_path / "vi.json"
    value_index.save(p)
    loaded = ValueIndex.load(p)
    assert loaded.inverted == value_index.inverted
