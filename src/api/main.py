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
import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from src.agent.cache import SemanticCache
from src.agent.graph import AgentResult, run_agent, stream_agent
from src.api.rate_limit import enforce_rate_limit
from src.api.run_stats import RunStats
from src.api.schemas import AskRequest, AskResponse
from src.config import settings
from src.db.catalog import DEFAULT_PAGE_SIZE, DEFAULT_SORT, MAX_PAGE_SIZE, list_games
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

_run_stats = RunStats()

FRIENDLY_ERROR_MESSAGE = (
    "We're experiencing high demand right now. Please try again in a moment."
)

DAILY_BUDGET_MESSAGE = (
    "This demo has reached its shared daily usage cap and will reset soon. "
    "Thanks for your patience -- please try again later."
)


class DailyBudgetExceeded(Exception):
    """Raised by _run_with_cache when the global daily token budget
    (settings.daily_token_budget) has been reached -- deliberately a
    distinct type, not a plain HTTPException raised at the check site:
    ask()'s own except Exception below overwrites any exception's detail
    with FRIENDLY_ERROR_MESSAGE in production, which would otherwise
    silently swallow this specific, honest, expected message."""


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
        "self_correction": _run_stats.as_dict(),
        "usage": _run_stats.usage_as_dict(),
        "deploy_commit": os.environ.get("RENDER_GIT_COMMIT"),
        # Render injects RENDER_GIT_COMMIT automatically for any service
        # deployed from a connected git repo (confirmed against Render's
        # own docs, Slice 45) -- no Dockerfile change needed. None locally
        # and in any environment that isn't Render itself, which is
        # honest: there's no deploy commit to report outside Render.
        # Added specifically so a live staleness question (see DOCEXP.md's
        # Slice 32/41 entries: is the deployed backend actually running
        # recent code, or did Auto-Deploy silently stop working) can be
        # checked automatically instead of requiring Render dashboard
        # access this session/CI has never had.
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


@app.get("/catalog")
def catalog(
    q: str | None = None,
    genre: str | None = None,
    sort: str = DEFAULT_SORT,
    order: str = "desc",
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> dict:
    """The full-catalog browse page (frontend's /catalog route) — search,
    genre filter, sort, and pagination, no LLM involved (src/db/catalog.py).
    `page_size` is capped the same way every other row-returning endpoint
    caps its limit."""
    if not Path(settings.duckdb_abs_path).exists():
        raise HTTPException(
            status_code=503,
            detail="Database not found. Run `python -m src.ingestion.ingest` first.",
        )
    capped_page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
    games, total = list_games(
        q=q, genre=genre, sort=sort, order=order, page=page, page_size=capped_page_size
    )
    return {"games": games, "total": total, "page": max(page, 1), "page_size": capped_page_size}


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
        attempts=result.attempts,
        tool_errors=result.tool_errors,
        total_tokens=result.total_tokens,
        estimated_cost_usd=result.estimated_cost_usd,
    )


def _record_real_run(result: AgentResult) -> None:
    """Only real runs count toward self-correction stats -- a cache hit
    replays a previous result verbatim, it doesn't run the graph again, so
    counting it here would double-count the same underlying run. Shared by
    both /ask and /ask/stream since each has its own real-run path."""
    _run_stats.record(result)
    if result.tool_errors > 0:
        logger.info(
            "self-correction: route=%s attempts=%d tool_errors=%d",
            result.route,
            result.attempts,
            result.tool_errors,
        )
    logger.info(
        "usage: route=%s total_tokens=%d estimated_cost_usd=%s",
        result.route,
        result.total_tokens,
        f"{result.estimated_cost_usd:.5f}" if result.estimated_cost_usd is not None else "unknown",
    )


def _run_with_cache(question: str) -> tuple[AgentResult, bool]:
    if settings.semantic_cache_enabled:
        hit = _cache.get(question)
        if hit is not None:
            cached_result, matched_question = hit
            logger.info("cache hit: %r ~ %r", question, matched_question)
            return cached_result, True

    # Checked only on a real cache miss, deliberately: a cached answer
    # costs nothing, so it should keep working even once the shared
    # budget below is exhausted for the day.
    if _run_stats.total_tokens >= settings.daily_token_budget:
        raise DailyBudgetExceeded()

    result = run_agent(question)
    _record_real_run(result)
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
    except DailyBudgetExceeded:
        raise HTTPException(status_code=503, detail=DAILY_BUDGET_MESSAGE) from None
    except Exception as exc:
        logger.exception("Agent run failed")
        detail = str(exc) if settings.debug else FRIENDLY_ERROR_MESSAGE
        raise HTTPException(status_code=503, detail=detail) from exc

    return _to_response(result, cached=cached)


def _sse(payload: dict) -> str:
    """One SSE-framed line: 'data: <json>\\n\\n'. Pulled out once ruff's
    line-length check flagged the third near-identical copy of this exact
    framing in ask_stream() below -- a real duplication, not just a long
    line to wrap."""
    return f"data: {json.dumps(payload)}\n\n"


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
                    yield _sse({"type": "final", "result": payload.model_dump()})
                    return

            # Same check and same reasoning as _run_with_cache's -- only
            # on a real cache miss, so a cached answer above still works
            # even once the shared budget is exhausted for the day.
            if _run_stats.total_tokens >= settings.daily_token_budget:
                yield _sse({"type": "error", "message": DAILY_BUDGET_MESSAGE})
                return

            final_result: AgentResult | None = None
            async for event in stream_agent(request.question):
                if event["type"] == "progress":
                    yield _sse(event)
                else:
                    final_result = event["result"]

            if final_result is not None:
                _record_real_run(final_result)
                if settings.semantic_cache_enabled:
                    _cache.put(request.question, final_result)
                payload = _to_response(final_result, cached=False)
                yield _sse({"type": "final", "result": payload.model_dump()})
        except Exception:
            logger.exception("Streaming agent run failed")
            yield _sse({"type": "error", "message": FRIENDLY_ERROR_MESSAGE})

    return StreamingResponse(event_stream(), media_type="text/event-stream")
