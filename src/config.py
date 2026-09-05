"""Central, typed config. Every module reads settings from here instead of
touching os.environ directly, so there is exactly one place that knows about
env vars.

The model provider is a single value (`model_provider`) — src/agent/llm_provider.py
is the only file allowed to branch on it. Nothing else in the agent should know
or care whether it's talking to Groq, Ollama, or (later) Gemini.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import truststore
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Populate os.environ from .env *before* Settings() runs. This is what lets
# LangSmith's tracer (which reads LANGSMITH_* straight from os.environ, not
# from our Settings object) pick up config without any extra plumbing.
load_dotenv(PROJECT_ROOT / ".env")

# Some environments (e.g. Windows machines with AV software like Avast doing
# TLS interception) re-sign HTTPS traffic with a locally-installed root CA
# that the OS trusts but Python's bundled `certifi` CA list does not, causing
# SSLCertVerificationError on every outbound request — hit this first with
# SteamSpy (requests) and again with fastembed's model download (httpx via
# huggingface_hub). truststore makes the stdlib ssl module use the OS trust
# store directly, which fixes it for every HTTP client in the process at
# once. Centralized here (config is imported by ~everything) instead of
# duplicated per-module.
truststore.inject_into_ssl()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- model provider ---
    model_provider: Literal["groq", "ollama", "gemini"] = "groq"

    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    groq_request_timeout_seconds: float = 45.0
    """Explicit ceiling on a single Groq HTTP call. Without this, ChatGroq
    falls back to the underlying SDK's own default (effectively unbounded
    for this app's purposes) — which is exactly what turned one slow
    cold-start request into a multi-minute hang/502 cycle instead of a
    clean, fast failure the one time this was actually hit in production
    (see DOCEXP.md's Slice 32 entry). A real request completes in single-
    digit seconds normally; 45s is generous headroom, not a tight budget."""
    groq_max_retries: int = 1
    """HTTP-client-level retries, on top of (not instead of) the agent's
    own SQL_MAX_RETRIES self-correction loop. Kept low deliberately: with
    the timeout above, a genuinely degraded provider fails in well under
    two minutes total instead of compounding delay across many attempts."""

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-1.5-flash"

    # --- embeddings / RAG (schema retrieval) ---
    embedding_provider: Literal["local", "ollama"] = "local"
    local_embedding_model: str = "BAAI/bge-small-en-v1.5"
    ollama_embedding_model: str = "nomic-embed-text"
    rag_top_k: int = 8

    # --- tracing ---
    langsmith_api_key: str = ""
    langsmith_project: str = "ai-game-analyst"
    langsmith_tracing: bool = False

    # --- database ---
    duckdb_path: str = "data/db/games.duckdb"

    # --- agent guardrails ---
    sql_max_retries: int = 3
    sql_max_rows: int = 200
    agent_retry_backoff_seconds: float = 3.0
    """Delay before a single retry after a model-call failure -- shared by
    agent_node (added Slice 44) and router_node (added Slice 44's item-3
    follow-up), the two places in the graph that call an LLM directly and
    have to survive it failing outright. A same-instant retry is
    genuinely useful against a one-off malformed-generation error, but
    close to useless against a real TPM rate limit -- the window that
    just got exceeded hasn't had a chance to roll forward yet. A few
    seconds is a real compromise for a live request (unlike
    run_evals.py's own much longer backoff, which a live user isn't
    sitting through)."""

    # --- ingestion ---
    steamspy_user_agent: str = "ai-game-analyst-ingest/0.1"
    ingest_game_count: int = 1000
    """1000 is the free ceiling with the current ingestion code — SteamSpy's
    bulk `all` listing returns ~1000 games per page, and ingest.py only
    fetches page 0. Going higher needs a code change to loop over more
    pages, not just a config bump."""

    # --- serving (Slice 6) ---
    debug: bool = False
    """When True, /ask error responses include the real exception message.
    False (the default, and what production should run with) returns a
    generic "high demand" message instead — see src/api/main.py."""

    semantic_cache_enabled: bool = True
    semantic_cache_similarity_threshold: float = 0.93
    """Calibrated empirically (see DOCEXP.md), not guessed: with the default
    local embedding model, a clear paraphrase of a cached question ("most
    owners" vs "highest number of owners") scored 0.957 similarity, while a
    related-but-different question ("most players" vs "most owners") scored
    0.834. 0.93 sits between them — catches genuine rephrasings without
    conflating two different questions into the same cached answer."""
    semantic_cache_max_entries: int = 200

    rate_limit_max_requests: int = 10
    rate_limit_window_seconds: float = 60.0

    cors_allowed_origins: str = "http://localhost:3000"
    """Comma-separated list of origins allowed to call the API — the
    Next.js frontend's dev/deployed URL(s)."""

    @property
    def duckdb_abs_path(self) -> str:
        p = Path(self.duckdb_path)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return str(p)


settings = Settings()
