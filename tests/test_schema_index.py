"""Tests for SchemaIndex's on-disk embedding cache (Slice 51 follow-up).
Uses the real local embedder (fastembed, no network) rather than a mock,
matching this project's own convention (see test_cache.py) -- what's
being tested here is real cache-file behavior, which a mocked embedder
would only pretend to exercise.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.agent.rag.schema_corpus import SchemaChunk
from src.agent.rag.schema_index import SchemaIndex, _corpus_hash
from src.config import settings

_CHUNKS = [
    SchemaChunk(id="a", kind="table", text="Table: games. One row per game."),
    SchemaChunk(id="b", kind="column", text="Column games.name: VARCHAR. Game title."),
]


@pytest.fixture()
def _cache_path(tmp_path, monkeypatch):
    path = tmp_path / "schema_index_cache.npz"
    monkeypatch.setattr(settings, "schema_index_cache_path", str(path))
    return path


def test_cache_miss_builds_and_saves(_cache_path):
    assert not _cache_path.exists()
    index = SchemaIndex(_CHUNKS)
    assert index._vectors.shape == (2, index._vectors.shape[1])
    assert _cache_path.exists()


def test_cache_hit_reuses_saved_vectors_without_recomputing(_cache_path, monkeypatch):
    first = SchemaIndex(_CHUNKS)
    saved_vectors = first._vectors.copy()

    # Replace the embedder with one that fails outright: if the second
    # construction below hits a real cache miss and tries to recompute,
    # this proves it by crashing instead of silently returning different
    # vectors that happen to look similar.
    import src.agent.rag.schema_index as schema_index_module

    def _boom():
        raise AssertionError("embedder should not be called on a cache hit")

    monkeypatch.setattr(schema_index_module, "get_embedder", _boom)
    second = SchemaIndex(_CHUNKS)

    np.testing.assert_array_equal(second._vectors, saved_vectors)


def test_stale_hash_triggers_a_rebuild_instead_of_serving_wrong_vectors(_cache_path):
    SchemaIndex(_CHUNKS)  # build the real cache once

    # Simulate schema_corpus.py having changed since the cache was built.
    data = np.load(_cache_path)
    np.savez(_cache_path, vectors=data["vectors"], hash=np.array("a-stale-hash"))

    rebuilt = SchemaIndex(_CHUNKS)
    # The cache file should have been overwritten with a fresh, valid hash.
    refreshed = np.load(_cache_path)
    assert str(refreshed["hash"]) == _corpus_hash(_CHUNKS)
    assert rebuilt._vectors.shape == (2, rebuilt._vectors.shape[1])


def test_a_corrupted_cache_file_degrades_to_recomputing_instead_of_crashing(_cache_path):
    _cache_path.write_text("not a real npz file")
    index = SchemaIndex(_CHUNKS)  # must not raise
    assert index._vectors.shape == (2, index._vectors.shape[1])


def test_corpus_hash_changes_when_a_chunk_s_text_changes():
    original = [SchemaChunk(id="a", kind="table", text="hello")]
    changed = [SchemaChunk(id="a", kind="table", text="hello world")]
    assert _corpus_hash(original) != _corpus_hash(changed)


def test_corpus_hash_is_stable_for_the_same_content():
    assert _corpus_hash(_CHUNKS) == _corpus_hash(list(_CHUNKS))
