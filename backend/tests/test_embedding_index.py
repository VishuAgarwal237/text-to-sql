"""Numpy-backed table embedding index. Skipped if numpy can't be imported in this environment."""

import pytest

pytest.importorskip("numpy")

from app.retrieval.embedding_index import TableEmbeddingIndex  # noqa: E402

_VOCAB = ["genre", "music", "style", "customer", "country", "sales", "revenue", "invoice", "total"]


def _fake_embed(texts):
    return [[float(t.lower().count(w)) for w in _VOCAB] for t in texts]


def test_build_and_query_ranks_by_similarity(catalog):
    idx = TableEmbeddingIndex.build(catalog, embed_fn=_fake_embed)
    ranked = idx.query("what was our total sales revenue", k=3, embed_fn=_fake_embed)
    assert ranked[0][0] == "Invoice"  # Invoice doc carries revenue/sales/total


def test_persistence_round_trip(catalog, tmp_path):
    idx = TableEmbeddingIndex.build(catalog, embed_fn=_fake_embed)
    idx.save(tmp_path)
    reloaded = TableEmbeddingIndex.load(tmp_path)
    assert reloaded.tables == idx.tables
    assert reloaded.query("revenue", k=1, embed_fn=_fake_embed)[0][0] == \
        idx.query("revenue", k=1, embed_fn=_fake_embed)[0][0]
