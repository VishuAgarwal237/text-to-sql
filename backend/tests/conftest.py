"""Shared fixtures: a seeded temp Chinook-lite SQLite DB, a matching catalog, and lightweight
fakes for the LLM and the embedding index so the whole pipeline runs offline (no network, no
numpy). The fakes exist because the real embedding index needs numpy and the real LLM needs a
provider — the decoupled node interfaces let us swap both for deterministic stand-ins."""

from __future__ import annotations

import json
import re
import sqlite3

import pytest

from app import db
from app.retrieval.embedding_index import table_document
from app.retrieval.value_index import ValueIndex
from app.schema.fk_graph import FKGraph
from app.state import Resources

# --- a real, tiny SQLite database with foreign keys + seed data ----------------------------
_DDL = """
CREATE TABLE Genre (GenreId INTEGER PRIMARY KEY, Name NVARCHAR(120));
CREATE TABLE Track (TrackId INTEGER PRIMARY KEY, Name NVARCHAR(200),
                    GenreId INTEGER REFERENCES Genre(GenreId));
CREATE TABLE InvoiceLine (InvoiceLineId INTEGER PRIMARY KEY,
                    TrackId INTEGER REFERENCES Track(TrackId),
                    UnitPrice NUMERIC(10,2), Quantity INTEGER);
CREATE TABLE Customer (CustomerId INTEGER PRIMARY KEY, Country NVARCHAR(40));
CREATE TABLE Invoice (InvoiceId INTEGER PRIMARY KEY,
                    CustomerId INTEGER REFERENCES Customer(CustomerId), Total NUMERIC(10,2));
"""
_SEED = [
    ("Genre", [(1, "Rock"), (2, "Latin")]),
    ("Track", [(1, "A", 1), (2, "B", 1), (3, "C", 2)]),
    ("InvoiceLine", [(1, 1, 0.99, 2), (2, 2, 0.99, 1), (3, 3, 1.99, 1)]),
    ("Customer", [(1, "Germany"), (2, "USA")]),
    ("Invoice", [(1, 1, 5.0), (2, 2, 3.0)]),
]


@pytest.fixture
def chinook_db(tmp_path, monkeypatch):
    """Create + seed a temp DB and point `app.db` at it (read-only access goes through db.py)."""
    path = tmp_path / "chinook_test.db"
    con = sqlite3.connect(path)
    con.executescript(_DDL)
    for table, rows in _SEED:
        placeholders = ",".join("?" * len(rows[0]))
        con.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)
    con.commit()
    con.close()
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


@pytest.fixture
def catalog():
    """A hand-written catalog matching the temp DB (mirrors what generate.py would produce)."""
    return {
        "tables": {
            "Genre": {"description": "music genres / styles", "synonyms": ["style"],
                      "columns": {"GenreId": {"type": "INTEGER"},
                                  "Name": {"type": "NVARCHAR", "synonyms": ["genre"]}}},
            "Track": {"description": "songs in the catalog", "columns": {
                "TrackId": {"type": "INTEGER"}, "Name": {"type": "NVARCHAR"},
                "GenreId": {"type": "INTEGER", "is_foreign_key": True, "references": "Genre.GenreId"}}},
            "InvoiceLine": {"description": "line items on invoices; per-track sales", "columns": {
                "TrackId": {"type": "INTEGER", "is_foreign_key": True, "references": "Track.TrackId"},
                "UnitPrice": {"type": "NUMERIC", "synonyms": ["price"]},
                "Quantity": {"type": "INTEGER"}}},
            "Customer": {"description": "customers who buy music", "columns": {
                "CustomerId": {"type": "INTEGER"},
                "Country": {"type": "NVARCHAR", "synonyms": ["country"]}}},
            "Invoice": {"description": "sales receipts / revenue per invoice",
                        "synonyms": ["revenue", "sales"], "columns": {
                            "InvoiceId": {"type": "INTEGER"},
                            "CustomerId": {"type": "INTEGER", "is_foreign_key": True,
                                           "references": "Customer.CustomerId"},
                            "Total": {"type": "NUMERIC", "synonyms": ["total", "revenue"]}}},
        },
        "relationships": [
            {"from": "Track.GenreId", "to": "Genre.GenreId", "join": "Track.GenreId = Genre.GenreId"},
            {"from": "InvoiceLine.TrackId", "to": "Track.TrackId",
             "join": "InvoiceLine.TrackId = Track.TrackId"},
            {"from": "Invoice.CustomerId", "to": "Customer.CustomerId",
             "join": "Invoice.CustomerId = Customer.CustomerId"},
        ],
    }


class FakeEmbedIndex:
    """Numpy-free stand-in for TableEmbeddingIndex: ranks tables by lexical overlap with the
    question. Good enough to exercise the hydration pipeline deterministically."""

    def __init__(self, catalog):
        self.catalog = catalog

    def query(self, question, k=30, embed_fn=None):
        qtok = set(re.findall(r"[a-z]+", question.lower()))
        scored = []
        for t, e in self.catalog["tables"].items():
            doc = set(re.findall(r"[a-z]+", table_document(t, e).lower()))
            scored.append((t, float(len(qtok & doc))))
        scored.sort(key=lambda x: -x[1])
        return scored[:k]


@pytest.fixture
def embed_index(catalog):
    return FakeEmbedIndex(catalog)


@pytest.fixture
def value_index(chinook_db, catalog):
    return ValueIndex.build(catalog)


@pytest.fixture
def fk_graph(catalog):
    return FKGraph.build(catalog)


class FakeLLM:
    """Callable(system, user) -> str. Dispatches by which prompt is in `system`; each kind maps
    to a JSON string or a queue of them (to script the repair loop). Records call kinds."""

    # Matched against the H1 title line only — the prompt *bodies* cross-reference each other
    # (e.g. sql_generation.md mentions "Schema Hydration"), so a whole-text search misroutes.
    _KINDS = [
        ("Router", "router"),
        ("Schema Hydration", "hydration"),
        ("SQL Generation", "sql"),
        ("Repair", "repair"),
        ("Presentation", "presentation"),
    ]

    def __init__(self, responses: dict[str, object]):
        self.responses = {k: (list(v) if isinstance(v, list) else v) for k, v in responses.items()}
        self.calls: list[str] = []

    def _kind(self, system: str) -> str:
        head = system.splitlines()[0]  # e.g. "# SQL Generation Agent — System Prompt"
        for needle, kind in self._KINDS:
            if needle in head:
                return kind
        raise AssertionError(f"Unrecognised prompt: {head!r}")

    def __call__(self, system: str, user: str) -> str:
        kind = self._kind(system)
        self.calls.append(kind)
        r = self.responses[kind]
        if isinstance(r, list):
            return r.pop(0)
        return r


def j(obj) -> str:
    return json.dumps(obj)


@pytest.fixture
def make_resources(catalog, embed_index, value_index, fk_graph):
    """Factory: given a complete_fn, build Resources wired to the temp DB + fakes."""

    def _make(complete_fn, **kw):
        return Resources(
            catalog=catalog, embed_index=embed_index, value_index=value_index,
            fk_graph=fk_graph, complete_fn=complete_fn, max_rows=kw.get("max_rows", 100),
            timeout_ms=kw.get("timeout_ms", 5000), max_retries=kw.get("max_retries", 2),
        )

    return _make
