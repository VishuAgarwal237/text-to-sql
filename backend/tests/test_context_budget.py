from app.schema import context_budget as cb


def test_estimate_tokens_positive():
    assert cb.estimate_tokens("hello world") >= 1


def test_render_table_includes_fk_and_synonyms(catalog):
    text = cb.render_table("InvoiceLine", catalog["tables"]["InvoiceLine"])
    assert "InvoiceLine" in text
    assert "-> Track.TrackId" in text  # FK rendered
    assert "price" in text  # column synonym rendered


def test_pack_respects_budget_and_reports_dropped(catalog):
    packed = cb.pack(["Genre", "Track", "InvoiceLine", "Customer", "Invoice"], catalog,
                     budget_tokens=15)
    # Highest-ranked always included; budget never blown by more than the first block.
    assert packed["included_tables"][0] == "Genre"
    assert packed["dropped_tables"]  # something was dropped under the tiny budget
    assert set(packed["included_tables"]) & set(packed["dropped_tables"]) == set()


def test_pack_force_includes_value_matches(catalog):
    packed = cb.pack(["Genre"], catalog, budget_tokens=1, always_include={"Customer"})
    # Even under an impossible budget, a forced (value-linked) table survives.
    assert "Customer" in packed["included_tables"]


def test_pack_skips_unknown_tables(catalog):
    packed = cb.pack(["Genre", "Ghost"], catalog, budget_tokens=10_000)
    assert "Ghost" not in packed["included_tables"]
