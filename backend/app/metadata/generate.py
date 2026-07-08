"""Incremental metadata-catalog generation.

Instead of documenting the entire schema in one giant request (which doesn't fit and goes stale
the moment any table changes), we:

  1. introspect the live schema + sample values per column,
  2. fingerprint each table and regenerate the doc **only for tables whose fingerprint moved**,
  3. derive relationships deterministically from the FK graph (no LLM needed, no drift),
  4. regenerate the global sections (common_metrics / join_paths / dialect_notes) only when the
     set of tables actually changed.

On a 5,000-table warehouse a nightly run then costs one LLM call per *changed* table, not 5,000.
The per-table prompt is derived from `backend/metadata/metadata_prompt.md` but scoped to a single
table so it stays small and verifiable.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from app import db, llm
from app.metadata import store

# One table's worth of documentation — the same 6 principles as the full-catalog prompt, scoped.
_TABLE_SYSTEM = (
    "You are a senior analytics engineer documenting one table of a production database so a "
    "downstream AI agent can translate business questions into correct SQL. You never invent "
    "columns not in the provided schema. You explain what each field MEANS and what questions it "
    "answers, not its data type. Return ONLY a single valid JSON object, no prose, no fences."
)

_TABLE_USER = """Document the single table below.

## Ground-truth schema (authoritative — do not add or rename anything)
{schema}

## Sample values (real, distinct values sampled per column)
{samples}

## OUTPUT CONTRACT — return exactly this JSON shape (one table entry):
{{
  "description": "<what one row represents and what business questions this table answers>",
  "grain": "<what a single row is>",
  "synonyms": ["<business terms a user might use for this table>"],
  "primary_key": ["<column(s)>"],
  "columns": {{
    "<ColumnName>": {{
      "type": "<sql type from the schema>",
      "description": "<business meaning>",
      "synonyms": ["<alternate phrasings, e.g. 'revenue' for a total>"],
      "is_foreign_key": <true|false>,
      "references": "<Table.Column or null>",
      "sample_values": ["<up to 5 representative values if provided>"],
      "notes": "<caveats: units, nullability, gotchas — omit if none>"
    }}
  }}
}}

Cover EVERY column. Make synonyms genuinely useful (how a non-technical analyst phrases things)."""


def _sample_table(table: str, schema_table: dict[str, Any], per_col: int = 8) -> dict[str, list]:
    """Sample low/mid-cardinality columns for grounding; skip obvious id/blob columns cheaply."""
    samples: dict[str, list] = {}
    for col in schema_table["columns"]:
        name = col["name"]
        # Sampling every column of every table is wasteful at scale; sample text/enum-ish columns.
        typ = (col["type"] or "").upper()
        if any(t in typ for t in ("BLOB", "REAL", "DOUBLE", "FLOAT")):
            continue
        try:
            vals = db.sample_column_values(table, name, limit=per_col)
        except Exception:
            continue
        if vals:
            samples[name] = [v for v, _ in vals]
    return samples


def _relationships_from_fks(schema: dict[str, Any]) -> list[dict[str, str]]:
    """Derive relationships directly from PRAGMA foreign_key_list — deterministic ground truth,
    so the join semantics can never drift from what the database actually enforces."""
    rels = []
    for table, t in schema.items():
        for fk in t["foreign_keys"]:
            frm = f'{table}.{fk["column"]}'
            to = f'{fk["references_table"]}.{fk["references_column"]}'
            rels.append({"from": frm, "to": to, "join": f"{frm} = {to}",
                         "description": f"Join {table} to {fk['references_table']}."})
    return rels


def generate_incremental(
    catalog_path=None,
    complete_fn: Callable[[str, str], str] = llm.complete,
    force: bool = False,
) -> dict[str, Any]:
    """Bring the on-disk catalog up to date with the live schema, regenerating only changed
    tables. Returns the updated catalog and writes it. `complete_fn` is injectable for tests."""
    catalog = store.load_catalog(catalog_path)
    schema = db.get_schema()
    fingerprints = catalog.setdefault("_fingerprints", {})
    tables_out = catalog.setdefault("tables", {})

    live_tables = set(schema)
    prior_tables = set(tables_out)
    regenerated: list[str] = []

    for table, tschema in schema.items():
        sample = _sample_table(table, tschema)
        fp = store.table_fingerprint(tschema, sample)
        if not force and not store.is_stale(catalog, table, fp):
            continue  # unchanged — keep the existing (possibly hand-tuned) doc
        raw = complete_fn(
            _TABLE_SYSTEM,
            _TABLE_USER.format(
                schema=json.dumps({table: tschema}, indent=2),
                samples=json.dumps(sample, indent=2, default=str),
            ),
        )
        entry = llm.parse_json(raw)
        _validate_table_entry(table, entry, tschema)  # every column must be real
        tables_out[table] = entry
        fingerprints[table] = fp
        regenerated.append(table)

    # Drop docs for tables that no longer exist.
    for gone in prior_tables - live_tables:
        tables_out.pop(gone, None)
        fingerprints.pop(gone, None)

    # Relationships are deterministic; refresh always (cheap).
    catalog["relationships"] = _relationships_from_fks(schema)

    # Global generative sections only need refreshing when the table set changed.
    if force or regenerated or (prior_tables != live_tables):
        catalog.setdefault("common_metrics", catalog.get("common_metrics", []))
        catalog.setdefault("join_paths", catalog.get("join_paths", []))
        catalog.setdefault("dialect_notes", catalog.get("dialect_notes", []))

    catalog["_changed_tables"] = regenerated
    store.save_catalog(catalog, catalog_path)
    return catalog


def _validate_table_entry(table: str, entry: dict, tschema: dict) -> None:
    """Reject a generated doc that invents columns or drops real ones — the catalog must stay
    faithful to ground truth or downstream SQL grounds on phantom columns."""
    real = {c["name"] for c in tschema["columns"]}
    documented = set(entry.get("columns", {}))
    invented = documented - real
    if invented:
        raise ValueError(f"{table}: metadata invented columns {sorted(invented)}")
    missing = real - documented
    if missing:
        raise ValueError(f"{table}: metadata omitted columns {sorted(missing)}")


if __name__ == "__main__":
    cat = generate_incremental()
    print(f"Regenerated {len(cat.get('_changed_tables', []))} table(s):",
          cat.get("_changed_tables"))
