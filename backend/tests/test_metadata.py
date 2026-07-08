"""Incremental metadata generation: regenerate only changed tables, derive relationships from
FKs, and reject docs that don't match ground truth."""

import json

import pytest

from app.metadata import generate, store


def _fake_meta_complete(system, user):
    """Parse the single-table schema out of the prompt and return a faithful doc for it."""
    marker = "do not add or rename anything)\n"
    start = user.index(marker) + len(marker)
    end = user.index("\n\n## Sample values")
    (table, tschema), = json.loads(user[start:end]).items()
    fk_cols = {fk["column"] for fk in tschema["foreign_keys"]}
    cols = {
        c["name"]: {"type": c["type"], "description": f"{c['name']} of {table}",
                    "is_foreign_key": c["name"] in fk_cols, "references": None}
        for c in tschema["columns"]
    }
    return json.dumps({"description": f"The {table} table", "grain": "one row",
                       "synonyms": [], "primary_key": [], "columns": cols})


def test_first_run_generates_all_and_derives_relationships(chinook_db, tmp_path):
    path = tmp_path / "catalog.json"
    cat = generate.generate_incremental(path, complete_fn=_fake_meta_complete)
    assert set(cat["tables"]) == {"Genre", "Track", "InvoiceLine", "Customer", "Invoice"}
    assert len(cat["_changed_tables"]) == 5
    # Relationships come from the FK graph, not the LLM.
    joins = {r["join"] for r in cat["relationships"]}
    assert "Track.GenreId = Genre.GenreId" in joins
    assert "Invoice.CustomerId = Customer.CustomerId" in joins


def test_second_run_is_noop(chinook_db, tmp_path):
    path = tmp_path / "catalog.json"
    generate.generate_incremental(path, complete_fn=_fake_meta_complete)
    cat = generate.generate_incremental(path, complete_fn=_fake_meta_complete)
    assert cat["_changed_tables"] == []  # nothing changed → no LLM regeneration


def test_only_stale_table_regenerates(chinook_db, tmp_path):
    path = tmp_path / "catalog.json"
    generate.generate_incremental(path, complete_fn=_fake_meta_complete)
    # Invalidate one table's fingerprint to simulate a schema/data change.
    cat = store.load_catalog(path)
    cat["_fingerprints"].pop("Genre")
    store.save_catalog(cat, path)

    calls = []

    def counting(system, user):
        calls.append(user)
        return _fake_meta_complete(system, user)

    out = generate.generate_incremental(path, complete_fn=counting)
    assert out["_changed_tables"] == ["Genre"]
    assert len(calls) == 1  # exactly one LLM call, for the one stale table


def test_force_regenerates_everything(chinook_db, tmp_path):
    path = tmp_path / "catalog.json"
    generate.generate_incremental(path, complete_fn=_fake_meta_complete)
    out = generate.generate_incremental(path, complete_fn=_fake_meta_complete, force=True)
    assert len(out["_changed_tables"]) == 5


def test_validate_rejects_invented_column():
    tschema = {"columns": [{"name": "GenreId"}, {"name": "Name"}], "foreign_keys": []}
    with pytest.raises(ValueError, match="invented"):
        generate._validate_table_entry("Genre", {"columns": {"GenreId": {}, "Ghost": {}}}, tschema)


def test_validate_rejects_missing_column():
    tschema = {"columns": [{"name": "GenreId"}, {"name": "Name"}], "foreign_keys": []}
    with pytest.raises(ValueError, match="omitted"):
        generate._validate_table_entry("Genre", {"columns": {"GenreId": {}}}, tschema)
