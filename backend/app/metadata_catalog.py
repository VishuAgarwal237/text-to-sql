"""Metadata-catalog verification (verification layer 5).

The LLM-authored metadata catalog (schema_metadata.json) is the ground truth every downstream
agent trusts, so before it is saved it must be checked against the *real* schema: every table,
column, and relationship it names must actually exist. This catches hallucinated or renamed
objects at generation time instead of at query time.

`validate_catalog` returns a list of error strings (empty == valid) so the generator can
reject a bad catalog with actionable messages.
"""

from __future__ import annotations

from typing import Any

from app import db


def _split_ref(ref: str) -> tuple[str, str] | None:
    """Parse a 'Table.Column' reference; return None if not that shape."""
    parts = ref.split(".")
    return (parts[0], parts[1]) if len(parts) == 2 else None


def validate_catalog(catalog: dict[str, Any], schema: dict[str, Any] | None = None) -> list[str]:
    """Validate `catalog` against the live schema. Returns a list of errors (empty == valid)."""
    if schema is None:
        schema = db.get_schema()

    real_cols: dict[str, set[str]] = {
        t: {c["name"] for c in info["columns"]} for t, info in schema.items()
    }
    errors: list[str] = []

    tables = catalog.get("tables")
    if not isinstance(tables, dict):
        return ["Catalog missing a 'tables' object."]

    # Every catalog table + column must exist in the real schema.
    for table, tinfo in tables.items():
        if table not in real_cols:
            errors.append(f"Unknown table: {table}")
            continue
        for col in (tinfo.get("columns") or {}):
            if col not in real_cols[table]:
                errors.append(f"Unknown column: {table}.{col}")

    # Every relationship endpoint must reference a real Table.Column.
    for rel in catalog.get("relationships", []) or []:
        for side in ("from", "to"):
            ref = rel.get(side)
            if not ref:
                continue
            parsed = _split_ref(ref)
            if not parsed:
                errors.append(f"Malformed relationship {side} reference: {ref!r}")
                continue
            t, c = parsed
            if t not in real_cols:
                errors.append(f"Relationship references unknown table: {ref}")
            elif c not in real_cols[t]:
                errors.append(f"Relationship references unknown column: {ref}")

    return errors
