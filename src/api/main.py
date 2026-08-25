"""FastAPI surface. Deliberately thin: this file only translates HTTP <->
the agent's run_agent()/stream_agent() calls, plus three serving concerns
that belong at this layer, not in the agent (a semantic cache, per-IP
rate limiting, graceful error responses). The agent itself still doesn't
import anything from FastAPI — see src/agent/graph.py — which is what
keeps the deployment target (resolved in Slice 6: Vercel for the frontend,
a separate Python host for this API — see DOCEXP.md) from ever leaking
into agent code.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from src.agent.cache import SemanticCache
from src.agent.graph import AgentResult, run_agent, stream_agent
from src.api.rate_limit import enforce_rate_limit
from src.api.schemas import AskRequest, AskResponse
from src.config import settings
from src.db.genre_stats import get_games_by_genre, get_genre_counts

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api")

app = FastAPI(title="AI Game Analyst", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

_cache: SemanticCache[AgentResult] = SemanticCache(
    similarity_threshold=settings.semantic_cache_similarity_threshold,
    max_entries=settings.semantic_cache_max_entries,
)

FRIENDLY_ERROR_MESSAGE = (
    "We're experiencing high demand right now. Please try again in a moment."
)


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
        "cache_entries": len(_cache),
    }


@app.get("/genres")
def genres() -> dict:
    """Live genre-prevalence stats for the frontend's genre showcase —
    computed from the DB on every request (src/db/genre_stats.py), not a
    count baked into frontend source, so it stays correct as the catalog
    grows/changes across ingestion re-runs."""
    if not Path(settings.duckdb_abs_path).exists():
        raise HTTPException(
            status_code=503,
            detail="Database not found. Run `python -m src.ingestion.ingest` first.",
        )
    return {"genres": get_genre_counts()}


@app.get("/games")
def games(genre: str, limit: int = 12) -> dict:
    """The actual games behind a genre showcase card — deterministic, no
    LLM involved (this is browsing the catalog, not asking a question of
    it). `limit` is capped the same way sql_max_rows caps everything else
    that returns rows."""
    if not Path(settings.duckdb_abs_path).exists():
        raise HTTPException(
            status_code=503,
            detail="Database not found. Run `python -m src.ingestion.ingest` first.",
        )
    capped_limit = min(max(limit, 1), settings.sql_max_rows)
    return {"games": get_games_by_genre(genre, capped_limit)}


def _to_response(result: AgentResult, *, cached: bool) -> AskResponse:
    return AskResponse(
        answer=result.answer,
        sql=result.sql,
        columns=result.columns,
        rows=result.rows,
        stats_result=result.stats_result,
        forecast_result=result.forecast_result,
        chart_spec=result.chart_spec,
        retrieved_schema_chunks=result.retrieved_chunk_ids,
        route=result.route,
        cached=cached,
    )


def _run_with_cache(question: str) -> tuple[AgentResult, bool]:
    if settings.semantic_cache_enabled:
        hit = _cache.get(question)
        if hit is not None:
            cached_result, matched_question = hit
            logger.info("cache hit: %r ~ %r", question, matched_question)
            return cached_result, True

    result = run_agent(question)
    if settings.semantic_cache_enabled:
        _cache.put(question, result)
    return result, False


@app.post("/ask", response_model=AskResponse, dependencies=[Depends(enforce_rate_limit)])
def ask(request: AskRequest) -> AskResponse:
    if not Path(settings.duckdb_abs_path).exists():
        raise HTTPException(
            status_code=503,
            detail="Database not found. Run `python -m src.ingestion.ingest` first.",
        )
    try:
        result, cached = _run_with_cache(request.question)
    except Exception as exc:  # noqa: BLE001 - never leak internals to the client by default
        logger.exception("Agent run failed")
        detail = str(exc) if settings.debug else FRIENDLY_ERROR_MESSAGE
        raise HTTPException(status_code=503, detail=detail) from exc

    return _to_response(result, cached=cached)


@app.post("/ask/stream", dependencies=[Depends(enforce_rate_limit)])
async def ask_stream(request: AskRequest) -> StreamingResponse:
    """Server-Sent Events: one `progress` event per graph node as it
    completes, then one `final` event with the same payload /ask returns.
    Lets the frontend show what the agent is doing (routing, retrieving
    schema, running a query...) instead of a bare spinner for however long
    the full graph takes — which, with retries, can be several seconds."""
    if not Path(settings.duckdb_abs_path).exists():
        raise HTTPException(
            status_code=503,
            detail="Database not found. Run `python -m src.ingestion.ingest` first.",
        )

    async def event_stream():
        try:
            if settings.semantic_cache_enabled:
                hit = _cache.get(request.question)
                if hit is not None:
                    cached_result, _ = hit
                    payload = _to_response(cached_result, cached=True)
                    yield f"data: {json.dumps({'type': 'final', 'result': payload.model_dump()})}\n\n"
                    return

            final_result: AgentResult | None = None
            async for event in stream_agent(request.question):
                if event["type"] == "progress":
                    yield f"data: {json.dumps(event)}\n\n"
                else:
                    final_result = event["result"]

            if final_result is not None:
                if settings.semantic_cache_enabled:
                    _cache.put(request.question, final_result)
                payload = _to_response(final_result, cached=False)
                yield f"data: {json.dumps({'type': 'final', 'result': payload.model_dump()})}\n\n"
        except Exception:
            logger.exception("Streaming agent run failed")
            detail = FRIENDLY_ERROR_MESSAGE
            yield f"data: {json.dumps({'type': 'error', 'message': detail})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
