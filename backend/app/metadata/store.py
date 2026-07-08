"""Metadata catalog store + change detection.

The catalog (`schema_metadata.json`) is the business-level description of every table/column
that the hydration agent reads. At scale it is too big and too slow to regenerate wholesale on
every schema change, so we fingerprint each table from its ground-truth schema + a value sample
and only regenerate the tables whose fingerprint moved. This module owns load/save and the
fingerprint; `generate.py` owns the LLM calls.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

DEFAULT_CATALOG_PATH = Path(
    os.environ.get(
        "SCHEMA_METADATA_PATH",
        str(Path(__file__).resolve().parents[2] / "data" / "schema_metadata.json"),
    )
)


def load_catalog(path: Path | None = None) -> dict[str, Any]:
    """Load the catalog, or an empty skeleton if it doesn't exist yet."""
    path = path or DEFAULT_CATALOG_PATH
    if not path.exists():
        return {"database": {}, "tables": {}, "relationships": [], "common_metrics": [],
                "join_paths": [], "dialect_notes": [], "_fingerprints": {}}
    return json.loads(path.read_text())


def save_catalog(catalog: dict[str, Any], path: Path | None = None) -> None:
    path = path or DEFAULT_CATALOG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(catalog, indent=2, sort_keys=False, default=str))


def table_fingerprint(table_schema: dict[str, Any], sample: dict[str, list]) -> str:
    """Stable hash of a table's ground truth: its columns (name+type+pk+fk) and a sampled set
    of values per column. Regeneration is triggered iff this changes — new column, retyped
    column, changed FK, or materially different data all move the hash; cosmetic edits don't."""
    payload = {
        "columns": table_schema.get("columns", []),
        "foreign_keys": table_schema.get("foreign_keys", []),
        # Sort sampled values so ordering noise doesn't cause spurious regeneration.
        "sample": {c: sorted(map(str, vs)) for c, vs in sorted(sample.items())},
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def is_stale(catalog: dict[str, Any], table: str, fingerprint: str) -> bool:
    """True if `table` is missing from the catalog or its stored fingerprint differs."""
    return catalog.get("_fingerprints", {}).get(table) != fingerprint
