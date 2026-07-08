"""Table embedding index — recall-oriented candidate generation.

At scale the full metadata catalog does not fit in a prompt, so this index answers a narrower
question: *which tables are even plausibly relevant to this question?* It embeds one document per
table (name + synonyms + description + column names/descriptions/synonyms) and returns the top-K
by cosine similarity.

Deliberately tuned for **recall, not precision**: K is generous and the scores are only used to
rank, not to hard-cut. The actual table choice is made downstream by the LLM reading the metadata
of these candidates — this stage just makes the catalog fit. A brute-force numpy cosine is fine
up to ~1e5 tables; past that, swap `query` for a real ANN store (FAISS/pgvector) behind the same
interface.

Persisted as an .npz (vectors) + .json (table order, model) so it survives restarts and is only
rebuilt for tables whose catalog entry changed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np

from app import llm

DEFAULT_INDEX_DIR = Path(
    os.environ.get("EMBED_INDEX_DIR", str(Path(__file__).resolve().parents[2] / "data" / "index"))
)


def table_document(table: str, entry: dict[str, Any]) -> str:
    """The text we embed for a table — everything a fuzzy question might match against."""
    parts = [table, entry.get("description", ""), entry.get("grain", "")]
    parts += entry.get("synonyms", [])
    for col, c in entry.get("columns", {}).items():
        parts.append(col)
        parts.append(c.get("description", ""))
        parts += c.get("synonyms", [])
    return " | ".join(p for p in parts if p)


def _normalize(m: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.clip(n, 1e-12, None)


class TableEmbeddingIndex:
    def __init__(self, tables: list[str], vectors: np.ndarray, model: str):
        self.tables = tables
        self.vectors = _normalize(vectors.astype(np.float32))
        self.model = model

    @classmethod
    def build(
        cls,
        catalog: dict[str, Any],
        embed_fn: Callable[[Sequence[str]], list[list[float]]] = llm.embed,
        model: str = llm.EMBED_MODEL,
        batch_size: int = 128,
    ) -> "TableEmbeddingIndex":
        tables = sorted(catalog.get("tables", {}))
        docs = [table_document(t, catalog["tables"][t]) for t in tables]
        vecs: list[list[float]] = []
        for i in range(0, len(docs), batch_size):
            vecs.extend(embed_fn(docs[i : i + batch_size]))
        return cls(tables, np.array(vecs, dtype=np.float32), model)

    def query(
        self,
        question: str,
        k: int = 30,
        embed_fn: Callable[[Sequence[str]], list[list[float]]] = llm.embed,
    ) -> list[tuple[str, float]]:
        """Top-K (table, score). K is generous by design — the LLM prunes, not this stage."""
        q = _normalize(np.array(embed_fn([question]), dtype=np.float32))
        sims = (self.vectors @ q[0])
        k = min(k, len(self.tables))
        idx = np.argpartition(-sims, k - 1)[:k]
        idx = idx[np.argsort(-sims[idx])]
        return [(self.tables[i], float(sims[i])) for i in idx]

    # --- persistence -------------------------------------------------------------------
    def save(self, index_dir: Path | None = None) -> None:
        d = index_dir or DEFAULT_INDEX_DIR
        d.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(d / "table_vectors.npz", vectors=self.vectors)
        (d / "table_index.json").write_text(json.dumps({"tables": self.tables, "model": self.model}))

    @classmethod
    def load(cls, index_dir: Path | None = None) -> "TableEmbeddingIndex":
        d = index_dir or DEFAULT_INDEX_DIR
        meta = json.loads((d / "table_index.json").read_text())
        vectors = np.load(d / "table_vectors.npz")["vectors"]
        return cls(meta["tables"], vectors, meta["model"])
