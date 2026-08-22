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

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Populate os.environ from .env *before* Settings() runs. This is what lets
# LangSmith's tracer (which reads LANGSMITH_* straight from os.environ, not
# from our Settings object) pick up config without any extra plumbing.
load_dotenv(PROJECT_ROOT / ".env")


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
