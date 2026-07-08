"""Value / entity index — literal disambiguation.

The hardest scale failure in text-to-SQL isn't picking a table, it's *value linking*: a user says
"customers in Germany" and there are 40 country-ish columns across the warehouse. This index maps
literal values back to the columns that contain them, so "Germany" resolves to the real
`Customer.Country` (and any siblings) instead of being guessed.

Build: for each low/mid-cardinality text-ish column, sample its distinct values (bounded scan) and
invert them into value-token -> (table, column, value). High-cardinality columns (ids, free text)
and numeric columns are skipped — they don't behave like enumerable entities.

Query: pull candidate literals out of the question (quoted spans, capitalized words/phrases) and
look them up. Returns, per literal, the columns that actually hold that value. These become both
extra table candidates and concrete filter hints handed to the LLM finalize step.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from app import db

DEFAULT_INDEX_PATH = Path(
    os.environ.get(
        "VALUE_INDEX_PATH", str(Path(__file__).resolve().parents[2] / "data" / "index" / "value_index.json")
    )
)

# Skip columns that don't behave like enumerable entities.
_MAX_DISTINCT = 500  # above this a column is treated as free-form / an id, not an entity set
_SKIP_TYPE = re.compile(r"INT|REAL|FLOAT|DOUBLE|BLOB|NUMERIC|DECIMAL|DATE|TIME", re.I)


def _norm(v: str) -> str:
    return re.sub(r"\s+", " ", str(v).strip().lower())


class ValueIndex:
    def __init__(self, inverted: dict[str, list[list[str]]]):
        # token -> list of [table, column, original_value]
        self.inverted = inverted

    @classmethod
    def build(cls, catalog: dict[str, Any], per_col: int = 200) -> "ValueIndex":
        inverted: dict[str, list[list[str]]] = {}
        for table, entry in catalog.get("tables", {}).items():
            for col, c in entry.get("columns", {}).items():
                if _SKIP_TYPE.search(c.get("type", "")):
                    continue
                try:
                    if db.approx_distinct_count(table, col) > _MAX_DISTINCT:
                        continue
                    values = db.sample_column_values(table, col, limit=per_col)
                except Exception:
                    continue
                for value, _count in values:
                    if value is None:
                        continue
                    key = _norm(value)
                    if not key or len(key) > 80:
                        continue
                    inverted.setdefault(key, []).append([table, col, str(value)])
                    # Also index individual tokens of multi-word values ("United Kingdom").
                    for tok in key.split():
                        if len(tok) >= 3:
                            inverted.setdefault(tok, []).append([table, col, str(value)])
        return cls(inverted)

    # Candidate literals: quoted spans + capitalized words/phrases + standalone tokens.
    _LITERAL = re.compile(r"'([^']+)'|\"([^\"]+)\"|\b([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)\b")

    def query(self, question: str, max_hits_per_literal: int = 8) -> dict[str, list[dict[str, str]]]:
        """Map each candidate literal in the question to the columns that contain it."""
        out: dict[str, list[dict[str, str]]] = {}
        seen_literals = set()
        for m in self._LITERAL.finditer(question):
            literal = next(g for g in m.groups() if g)
            key = _norm(literal)
            if key in seen_literals:
                continue
            seen_literals.add(key)
            hits = self.inverted.get(key, [])
            if not hits:  # fall back to token overlap for multiword literals
                for tok in key.split():
                    hits += self.inverted.get(tok, [])
            if hits:
                # De-dup by (table,column,value), keep order, cap.
                uniq, seen = [], set()
                for t, c, v in hits:
                    sig = (t, c, v)
                    if sig not in seen:
                        seen.add(sig)
                        uniq.append({"table": t, "column": c, "value": v})
                    if len(uniq) >= max_hits_per_literal:
                        break
                out[literal] = uniq
        return out

    def candidate_tables(self, question: str) -> set[str]:
        """Tables implied purely by value matches — folded into the retrieval candidate set so a
        table the embedding step ranked low still surfaces if it literally holds a mentioned value."""
        return {h["table"] for hits in self.query(question).values() for h in hits}

    def save(self, path: Path | None = None) -> None:
        p = path or DEFAULT_INDEX_PATH
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.inverted))

    @classmethod
    def load(cls, path: Path | None = None) -> "ValueIndex":
        p = path or DEFAULT_INDEX_PATH
        return cls(json.loads(p.read_text()))
