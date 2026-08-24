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
    groq_model: str = "llama-3.3-70b-versatile"

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

    # --- ingestion ---
    steamspy_user_agent: str = "ai-game-analyst-ingest/0.1"
    ingest_game_count: int = 200

    @property
    def duckdb_abs_path(self) -> str:
        p = Path(self.duckdb_path)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return str(p)


settings = Settings()
