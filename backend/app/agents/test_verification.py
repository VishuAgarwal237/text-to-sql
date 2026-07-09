"""Tests for verification layers 2-5 (run against the live Chinook DB)."""

import pytest

from app import db
from app.agents.contract import ContractError, parse_agent_json
from app.agents.repair_loop import validate_and_repair
from app.agents.validator import validate
from app.metadata_catalog import validate_catalog


# --- Layer 2: structural validation -------------------------------------------------------

def test_valid_select_passes():
    res = validate("SELECT Name FROM Genre LIMIT 3")
    assert res.ok and res.stage == "ok"


def test_write_rejected_at_read_only_stage():
    res = validate("DELETE FROM Artist")
    assert not res.ok and res.stage == "read_only"


def test_syntax_error_caught_at_parse_stage():
    res = validate("SELECT FROM WHERE")
    assert not res.ok and res.stage == "parse"


def test_bad_column_caught_at_bind_stage():
    # Parses fine, but NoSuchColumn only surfaces when bound against the real schema.
    res = validate("SELECT NotAColumn FROM Genre")
    assert not res.ok and res.stage == "bind"


# --- Layer 3: validate <-> repair loop ----------------------------------------------------

def test_repair_loop_fixes_then_passes():
    # First SQL has a bad column; the repair callback fixes it on attempt 1.
    def repair_fn(sql, error, stage, attempt):
        return "SELECT Name FROM Genre LIMIT 1"

    out = validate_and_repair("SELECT Nope FROM Genre", repair_fn, max_retries=3)
    assert out.ok and out.attempts == 1


def test_repair_loop_exhausts_budget():
    def repair_fn(sql, error, stage, attempt):
        return "SELECT StillWrong FROM Genre"  # never fixes it

    out = validate_and_repair("SELECT Nope FROM Genre", repair_fn, max_retries=2)
    assert not out.ok and out.attempts == 2


# --- Layer 4: agent JSON contract ---------------------------------------------------------

def test_contract_accepts_fenced_json():
    raw = '```json\n{"status":"success","sql":"SELECT 1","result":"ok"}\n```'
    data = parse_agent_json(raw, "sql_generation")
    assert data["sql"] == "SELECT 1"


def test_contract_rejects_missing_key():
    with pytest.raises(ContractError):
        parse_agent_json('{"status":"success"}', "sql_generation")  # no sql/result


def test_contract_rejects_non_json():
    with pytest.raises(ContractError):
        parse_agent_json("I could not answer that.", "router")


# --- Layer 5: metadata catalog validation -------------------------------------------------

def test_catalog_valid_against_real_schema():
    schema = db.get_schema()
    catalog = {"tables": {"Genre": {"columns": {"GenreId": {}, "Name": {}}}}}
    assert validate_catalog(catalog, schema) == []


def test_catalog_flags_hallucinated_objects():
    schema = db.get_schema()
    catalog = {
        "tables": {
            "Genre": {"columns": {"GenreId": {}, "Bogus": {}}},
            "MadeUpTable": {"columns": {}},
        },
        "relationships": [{"from": "Genre.GenreId", "to": "Ghost.Id"}],
    }
    errors = validate_catalog(catalog, schema)
    assert any("Bogus" in e for e in errors)
    assert any("MadeUpTable" in e for e in errors)
    assert any("Ghost" in e for e in errors)
