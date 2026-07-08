"""Production resource construction.

Tests inject `Resources` directly. Runtime and eval code need one canonical path that loads the
metadata catalog, builds or loads retrieval indexes, builds the FK graph, and returns the same
`Resources` object the graph nodes already consume.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from app import llm
from app.metadata import store
from app.retrieval.embedding_index import DEFAULT_INDEX_DIR, TableEmbeddingIndex
from app.retrieval.value_index import DEFAULT_INDEX_PATH, ValueIndex
from app.schema.fk_graph import FKGraph
from app.state import Resources


def _require_catalog(catalog: dict[str, Any], catalog_path: Path | None) -> None:
    if catalog.get("tables"):
        return
    path = catalog_path or store.DEFAULT_CATALOG_PATH
    raise FileNotFoundError(
        f"No schema metadata catalog found at {path}. "
        "Run `python -m app.metadata.generate` first, or set SCHEMA_METADATA_PATH."
    )


def _load_or_build_embedding_index(
    catalog: dict[str, Any],
    *,
    rebuild: bool,
    save: bool,
    embed_fn: Callable = llm.embed,
) -> TableEmbeddingIndex:
    if not rebuild:
        try:
            return TableEmbeddingIndex.load(DEFAULT_INDEX_DIR)
        except FileNotFoundError:
            pass
    index = TableEmbeddingIndex.build(catalog, embed_fn=embed_fn)
    if save:
        index.save(DEFAULT_INDEX_DIR)
    return index


def _load_or_build_value_index(
    catalog: dict[str, Any],
    *,
    rebuild: bool,
    save: bool,
) -> ValueIndex:
    if not rebuild:
        try:
            return ValueIndex.load(DEFAULT_INDEX_PATH)
        except FileNotFoundError:
            pass
    index = ValueIndex.build(catalog)
    if save:
        index.save(DEFAULT_INDEX_PATH)
    return index


def build_resources(
    *,
    catalog_path: Path | None = None,
    complete_fn: Callable[[str, str], str] = llm.complete,
    embed_fn: Callable = llm.embed,
    rebuild_indexes: bool = False,
    save_indexes: bool = True,
    max_retries: int = 2,
    max_rows: int = 1000,
    timeout_ms: int = 5000,
    candidate_k: int = 30,
    budget_tokens: int = 6000,
) -> Resources:
    """Build runtime resources from on-disk metadata and indexes.

    The metadata catalog is authoritative. Retrieval indexes are derived acceleration structures:
    load them if present, otherwise build and optionally persist them.
    """
    catalog = store.load_catalog(catalog_path)
    _require_catalog(catalog, catalog_path)
    return Resources(
        catalog=catalog,
        embed_index=_load_or_build_embedding_index(
            catalog, rebuild=rebuild_indexes, save=save_indexes, embed_fn=embed_fn
        ),
        value_index=_load_or_build_value_index(catalog, rebuild=rebuild_indexes, save=save_indexes),
        fk_graph=FKGraph.build(catalog),
        complete_fn=complete_fn,
        embed_fn=embed_fn,
        max_retries=max_retries,
        max_rows=max_rows,
        timeout_ms=timeout_ms,
        candidate_k=candidate_k,
        budget_tokens=budget_tokens,
    )
