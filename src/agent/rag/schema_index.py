"""A small in-memory vector index over the schema corpus, and the function
that turns retrieved chunks back into prompt text.

Deliberately brute-force (embed everything once, rank by dot product on
every query) rather than a real vector store (Chroma/FAISS/pgvector): the
corpus is ~20 short chunks. A linear scan over 20 384-dim vectors is
microseconds — a real ANN index would add a dependency and operational
surface (persistence, index files) to solve a problem this scale doesn't
have. Revisit if the corpus grows into the hundreds of chunks (e.g. many
tables' worth of columns + metrics), where brute-force scanning would still
work but a proper store would start being the more honest architecture.
"""

from __future__ import annotations

import numpy as np

from src.agent.rag.embeddings import get_embedder
from src.agent.rag.schema_corpus import SCHEMA_CHUNKS, SchemaChunk


class SchemaIndex:
    def __init__(self, chunks: list[SchemaChunk]):
        self.chunks = chunks
        self._vectors = get_embedder().embed_texts([c.text for c in chunks])

    def retrieve(self, query: str, top_k: int) -> list[SchemaChunk]:
        """Always include chunks marked always_include (cheap, and some
        context — e.g. that the table exists, that a `name` column exists —
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
