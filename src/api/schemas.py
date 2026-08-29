from __future__ import annotations

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(
        min_length=1, description="A plain-English question about the games catalog."
    )


class AskResponse(BaseModel):
    answer: str
    sql: str | None = None
    columns: list[str] | None = None
    rows: list[list] | None = None
    stats_result: dict | None = None
    forecast_result: dict | None = None
    chart_spec: dict | None = None
    retrieved_schema_chunks: list[str] | None = None
    route: str | None = None
    cached: bool = False
    attempts: int = 0
    """Total tool-call round trips this question took. 1 is normal for a
    single-fact lookup; higher can mean either a legitimate multi-step
    question or a self-correction retry -- see tool_errors to tell which."""
    tool_errors: int = 0
    """How many of those tool calls actually failed and had to be
    self-corrected. 0 means the model got it right first try every time."""
    total_tokens: int = 0
    estimated_cost_usd: float | None = None
    """Real token usage/cost for this question's LLM calls (Groq on-demand
    list price, not including any provider prompt-caching discount -- see
    src/agent/pricing.py). None only if the configured model has no known
    price entry there, not if this was a cache hit (a cache hit still
    replays the real cost the original run incurred)."""
