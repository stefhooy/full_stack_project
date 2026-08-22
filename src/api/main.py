"""FastAPI surface. Deliberately thin: this file only translates HTTP <->
the agent's run_agent() call. All the actual logic (LLM, SQL guard,
LangGraph loop) lives in src/agent and src/db and doesn't import anything
from FastAPI — that keeps the agent runnable standalone (see
scripts/ask_cli.py-style usage in README) and keeps the deployment target
(Vercel Python function vs. a separate Python host, still an open decision
— see DOCEXP.md) from leaking into the agent code.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException

from src.agent.graph import run_agent
from src.api.schemas import AskRequest, AskResponse
from src.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api")

app = FastAPI(title="AI Game Analyst", version="0.1.0")


@app.on_event("startup")
def check_db_exists() -> None:
    if not Path(settings.duckdb_abs_path).exists():
        logger.warning(
            "DuckDB file not found at %s. Run ingestion first: "
            "python -m src.ingestion.ingest",
            settings.duckdb_abs_path,
        )


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "db_exists": Path(settings.duckdb_abs_path).exists(),
        "model_provider": settings.model_provider,
    }


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest) -> AskResponse:
    if not Path(settings.duckdb_abs_path).exists():
        raise HTTPException(
            status_code=503,
            detail="Database not found. Run `python -m src.ingestion.ingest` first.",
        )
    try:
        result = run_agent(request.question)
    except Exception as exc:  # noqa: BLE001 - surface any agent failure as a 500 with detail
        logger.exception("Agent run failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return AskResponse(
        answer=result.answer,
        sql=result.sql,
        columns=result.columns,
        rows=result.rows,
    )
