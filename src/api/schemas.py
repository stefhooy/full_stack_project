from __future__ import annotations

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=1, description="A plain-English question about the games catalog.")


class AskResponse(BaseModel):
    answer: str
    sql: str | None = None
    columns: list[str] | None = None
    rows: list[list] | None = None
    stats_result: dict | None = None
    chart_spec: dict | None = None
    retrieved_schema_chunks: list[str] | None = None
    route: str | None = None
    cached: bool = False
