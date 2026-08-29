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
