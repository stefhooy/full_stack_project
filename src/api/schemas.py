from __future__ import annotations

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(
        min_length=1, description="A plain-English question about the games catalog."
    )
    prior_question: str | None = Field(
        default=None,
        description=(
            "Set only when this question is completing a clarifying question Ludo just "
            "asked (Slice 63's one-hop follow-up) -- the original question that "
            "produced it. Sent alongside prior_clarifying_question; combined into one "
            "resolved question at the API layer before the agent ever sees it, so the "
            "graph itself stays single-question-in, single-answer-out."
        ),
    )
    prior_clarifying_question: str | None = Field(
        default=None,
        description="The clarifying question Ludo asked, paired with prior_question above.",
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
    awaiting_reply: bool = False
    """True only for a genuinely answerable clarifying question -- the
    frontend shows a one-hop reply box (not a hard-stop message like a
    rate limit) only when this is true. See AgentState.awaiting_reply's
    own comment in src/agent/graph.py for why the two cases need to stay
    distinct."""
    follow_up_suggestions: list[str] | None = None
    """Up to 3 deterministic, zero-cost suggested next questions (never
    set for a needs_clarification answer). See src/agent/follow_ups.py."""
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
