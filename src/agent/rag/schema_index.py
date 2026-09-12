"""A small in-memory vector index over the schema corpus, and the function
that turns retrieved chunks back into prompt text.

Deliberately brute-force (embed everything once, rank by dot product on
every query) rather than a real vector store (Chroma/FAISS/pgvector): the
corpus is ~20 short chunks. A linear scan over 20 384-dim vectors is
microseconds, a real ANN index would add a dependency and operational
surface (persistence, index files) to solve a problem this scale doesn't
have. Revisit if the corpus grows into the hundreds of chunks (e.g. many
tables' worth of columns + metrics), where brute-force scanning would still
work but a proper store would start being the more honest architecture.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

from src.agent.rag.embeddings import get_embedder
from src.agent.rag.schema_corpus import SCHEMA_CHUNKS, SchemaChunk
from src.config import settings


def _corpus_hash(chunks: list[SchemaChunk]) -> str:
    """Identifies exactly this corpus's content, not just its length --
    changing a single chunk's text changes this. Used to detect a stale
    on-disk cache (schema_corpus.py edited since the cache was built)
    rather than silently serving embeddings for text that no longer
    matches."""
    joined = "\x00".join(c.text for c in chunks)  # NUL: never appears in
    # real chunk text, so it can't produce a false collision the way an
    # ordinary separator (a space, a newline) that a chunk might contain
    # could.
    return hashlib.sha256(joined.encode()).hexdigest()


class SchemaIndex:
    def __init__(self, chunks: list[SchemaChunk]):
        self.chunks = chunks
        self._vectors = self._load_or_build_vectors(chunks)

    def _load_or_build_vectors(self, chunks: list[SchemaChunk]) -> np.ndarray:
        # Precomputed once (Slice 51 follow-up) rather than embedding the
        # corpus live on every fresh process start: the corpus is static
        # text baked into schema_corpus.py, so its embeddings are the
        # same every single time unless that file itself changes --
        # recomputing them live on every restart was pure waste, and (see
        # the one-at-a-time comment below) was also the direct cause of a
        # real production OOM incident. A cache file under settings'
        # PROJECT_ROOT-relative path (not /tmp -- see DOCEXP.md's Slice 49
        # entry for exactly why that distinction matters on Render)
        # persists across restarts once built once, at Docker build time,
        # by the Dockerfile's existing pre-warm step.
        cache_path = Path(settings.schema_index_cache_abs_path)
        expected_hash = _corpus_hash(chunks)
        if cache_path.exists():
            try:
                cached = np.load(cache_path, allow_pickle=False)
                if str(cached["hash"]) == expected_hash:
                    return np.asarray(cached["vectors"])
            except Exception:  # noqa: BLE001 -- any cache-read problem
                # (corrupt file, incompatible npz format after a numpy
                # upgrade, permissions) should degrade to recomputing,
                # never crash a real request over a cache that's
                # supposed to be a pure optimization.
                pass

        # Embedded ONE AT A TIME, not as a single embed_texts() batch call
        # -- a real, measured production incident (DOCEXP.md's Slice 50),
        # not a style preference. Batching pads every text in the call up
        # to the length of the longest one so they can be processed
        # together; this corpus's chunks range from 54 to 1,465
        # characters (a real, current outlier -- column:name's detailed
        # guidance), so one long chunk was dragging the whole batch's
        # memory cost up to its own scale: measured at +445.6MB batched,
        # vs. +11.5MB for this same real corpus one at a time -- enough
        # on its own to exceed Render's actual 512MB free-tier ceiling
        # and OOM-kill the process on every real question. Each chunk's
        # own embedding is identical either way; only the batching
        # changes, and with it, the memory profile.
        embedder = get_embedder()
        vectors = np.array([embedder.embed_query(c.text) for c in chunks])

        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            np.savez(cache_path, vectors=vectors, hash=expected_hash)
        except OSError:
            # A read-only filesystem or similar just means no caching
            # benefit next restart, not a reason to fail this request --
            # the vectors just computed are still returned and used below.
            pass

        return vectors

    def retrieve(self, query: str, top_k: int) -> list[SchemaChunk]:
        """Always include chunks marked always_include (cheap, and some
        context, e.g. that the table exists, that a `name` column exists -
        is structurally relevant regardless of semantic similarity to the
        query), plus the top_k most similar remaining chunks by cosine
        similarity to the query."""
        always_idx = [i for i, c in enumerate(self.chunks) if c.always_include]
        rest_idx = [i for i, c in enumerate(self.chunks) if not c.always_include]

        query_vector = get_embedder().embed_query(query)
        similarities = self._vectors[rest_idx] @ query_vector
        ranked = np.argsort(-similarities)[:top_k]
        top_rest_idx = [rest_idx[i] for i in ranked]

        return [self.chunks[i] for i in always_idx + top_rest_idx]


_index: SchemaIndex | None = None


def get_schema_index() -> SchemaIndex:
    global _index
    if _index is None:
        _index = SchemaIndex(SCHEMA_CHUNKS)
    return _index


def assemble_schema_text(chunks: list[SchemaChunk]) -> str:
    table_lines = [c.text for c in chunks if c.kind == "table"]
    column_lines = [c.text for c in chunks if c.kind == "column"]
    metric_lines = [c.text for c in chunks if c.kind == "metric_note"]

    parts = list(table_lines)
    if column_lines:
        parts.append("\nRelevant columns:")
        parts.extend(f"  - {line}" for line in column_lines)
    if metric_lines:
        parts.append("\nRelevant notes:")
        parts.extend(f"  - {line}" for line in metric_lines)
    return "\n".join(parts)
