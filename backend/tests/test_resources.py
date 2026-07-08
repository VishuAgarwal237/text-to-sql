from pathlib import Path

import pytest

from app import resources
from app.retrieval.value_index import ValueIndex


class DummyEmbeddingIndex:
    @classmethod
    def load(cls, _path):
        raise FileNotFoundError

    @classmethod
    def build(cls, catalog, embed_fn):
        return cls()

    def save(self, _path):
        pass


def test_build_resources_requires_metadata_catalog(tmp_path):
    with pytest.raises(FileNotFoundError, match="schema metadata catalog"):
        resources.build_resources(catalog_path=tmp_path / "missing.json")


def test_build_resources_loads_catalog_and_builds_missing_indexes(monkeypatch, catalog, tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text(__import__("json").dumps(catalog))

    monkeypatch.setattr(resources.TableEmbeddingIndex, "load", lambda _path: (_ for _ in ()).throw(FileNotFoundError))
    monkeypatch.setattr(resources.TableEmbeddingIndex, "build", lambda catalog, embed_fn: DummyEmbeddingIndex())
    monkeypatch.setattr(resources.ValueIndex, "load", lambda _path: (_ for _ in ()).throw(FileNotFoundError))
    monkeypatch.setattr(resources.ValueIndex, "build", lambda catalog: ValueIndex({}))

    res = resources.build_resources(
        catalog_path=Path(path),
        embed_fn=lambda texts: [[1.0] for _ in texts],
        save_indexes=False,
    )

    assert set(res.catalog["tables"]) == set(catalog["tables"])
    assert res.fk_graph is not None
