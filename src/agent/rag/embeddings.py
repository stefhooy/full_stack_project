"""The embeddings equivalent of src/agent/llm_provider.py: one seam,
one config value (`EMBEDDING_PROVIDER`), everything else just calls
get_embedder() and gets back something with .embed_texts() / .embed_query().

Default is "local" — an ONNX model running in-process via fastembed. No API
key, no network call at query time (one-time model download on first use,
cached to disk after), and it works the same whether MODEL_PROVIDER is
Groq, Ollama, or (later) Gemini. Chosen specifically because Groq has no
embeddings endpoint at all, so "whatever LLM provider is configured" was
never going to be a valid default here — this needed its own decision.

Note: fastembed's typical model output is already L2-normalized, but every
implementation here normalizes explicitly so that `vectors @ query_vector`
in schema_index.py is guaranteed to be cosine similarity regardless of
provider.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

from src.config import settings


class Embedder(Protocol):
    def embed_texts(self, texts: list[str]) -> np.ndarray: ...
    def embed_query(self, text: str) -> np.ndarray: ...


def _normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


class LocalEmbedder:
    """In-process ONNX embeddings via fastembed. No API key, no server."""

    def __init__(self, model_name: str):
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=model_name)

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        return _normalize(np.array(list(self._model.embed(texts))))

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_texts([text])[0]


class OllamaEmbedder:
    """Local dev alternative: embeddings via a running Ollama daemon."""

    def __init__(self, model_name: str, base_url: str):
        from langchain_ollama import OllamaEmbeddings

        self._model = OllamaEmbeddings(model=model_name, base_url=base_url)

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        return _normalize(np.array(self._model.embed_documents(texts)))

    def embed_query(self, text: str) -> np.ndarray:
        return _normalize(np.array([self._model.embed_query(text)]))[0]


_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    """Cached singleton — building a LocalEmbedder loads the ONNX model into
    memory, and Ollama's client is cheap but no reason to rebuild per call."""
    global _embedder
    if _embedder is not None:
        return _embedder

    provider = settings.embedding_provider
    if provider == "local":
        _embedder = LocalEmbedder(settings.local_embedding_model)
    elif provider == "ollama":
        _embedder = OllamaEmbedder(settings.ollama_embedding_model, settings.ollama_base_url)
    else:
        raise ValueError(f"Unknown EMBEDDING_PROVIDER: {provider!r}")
    return _embedder
