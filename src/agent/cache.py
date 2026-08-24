"""A semantic cache for /ask: if a new question embeds close enough to a
question we've already answered, return the cached AgentResult instead of
re-running the full graph (router LLM call + retrieval + agent LLM call(s)
+ possible retries).

Reuses the same embedding provider seam from Slice 2's RAG retrieval
(src/agent/rag/embeddings.py) rather than introducing a second embedding
mechanism — "semantic similarity between two short texts" is the same
problem whether it's a question against a schema chunk or a question
against another question.

Deliberately in-memory, not Redis/a real cache service: this is a single
FastAPI process (see the deployment note in DOCEXP.md — the chosen host is
a normal long-running service, not horizontally-scaled serverless, so a
process-local cache is coherent across requests within that process). A
real multi-instance deployment would need a shared cache; noted as an open
question rather than solved speculatively here.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Generic, TypeVar

import numpy as np

from src.agent.rag.embeddings import get_embedder

T = TypeVar("T")


@dataclass
class _CacheEntry(Generic[T]):
    question: str
    vector: np.ndarray
    value: T
    created_at: float = field(default_factory=time.monotonic)


class SemanticCache(Generic[T]):
    def __init__(self, similarity_threshold: float = 0.96, max_entries: int = 200):
        self.similarity_threshold = similarity_threshold
        self.max_entries = max_entries
        self._entries: list[_CacheEntry[T]] = []

    def get(self, question: str) -> tuple[T, str] | None:
        """Returns (cached_value, matched_question) on a hit, else None."""
        if not self._entries:
            return None
        query_vector = get_embedder().embed_query(question)
        vectors = np.array([e.vector for e in self._entries])
        similarities = vectors @ query_vector
        best_idx = int(np.argmax(similarities))
        if similarities[best_idx] >= self.similarity_threshold:
            entry = self._entries[best_idx]
            return entry.value, entry.question
        return None

    def put(self, question: str, value: T) -> None:
        vector = get_embedder().embed_query(question)
        self._entries.append(_CacheEntry(question=question, vector=vector, value=value))
        if len(self._entries) > self.max_entries:
            self._entries.pop(0)  # evict oldest (simple FIFO, not LRU)

    def __len__(self) -> int:
        return len(self._entries)
