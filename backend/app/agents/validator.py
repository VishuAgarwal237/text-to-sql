"""Deterministic SQL validation node (verification layers 1 + 2).

This is the non-LLM guard that every generated query passes through before execution. It is
intentionally pure code — exact and cheap, not generative. On failure it returns a precise,
stage-tagged error that the Repair agent can act on.

Three stages, cheapest first:
  1. **read_only**  — reuse `db.assert_read_only`: single statement, SELECT/WITH only, no
     mutating keyword. (Also the security guard.)
  2. **parse**      — `sqlglot` parses the SQL in the SQLite dialect and confirms it is
     exactly one statement. Catches syntax errors without touching the DB.
  3. **bind**       — `db.explain` runs `EXPLAIN <sql>`, which binds the query against the
     real schema (resolving tables/columns) WITHOUT executing it. Catches "no such column",
     bad joins, GROUP BY errors, etc.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import sqlglot

from app import db


@dataclass
class ValidationResult:
    ok: bool
    stage: str          # "read_only" | "parse" | "bind" | "ok"
    error: str | None    # human/LLM-readable error, or None on success
    sql: str            # the cleaned SQL (comment-stripped, single statement)

    def __bool__(self) -> bool:
        return self.ok


def validate(sql: str) -> ValidationResult:
    """Validate `sql` through all three stages. Returns the first failure, or ok."""
    # Stage 1: read-only / single-statement guard.
    try:
        cleaned = db.assert_read_only(sql)
    except db.UnsafeSQLError as exc:
        return ValidationResult(False, "read_only", str(exc), sql)

    # Stage 2: syntactic parse in the SQLite dialect (no DB access).
    try:
        statements = sqlglot.parse(cleaned, dialect="sqlite")
    except sqlglot.errors.ParseError as exc:
        return ValidationResult(False, "parse", f"SQL parse error: {exc}", cleaned)
    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        return ValidationResult(
            False, "parse", f"Expected exactly one statement, found {len(statements)}.", cleaned
        )

    # Stage 3: bind against the real schema via EXPLAIN (no execution).
    try:
        db.explain(cleaned)
    except sqlite3.Error as exc:
        return ValidationResult(False, "bind", f"Schema/binding error: {exc}", cleaned)

    return ValidationResult(True, "ok", None, cleaned)
