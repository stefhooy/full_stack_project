"""The supervisor-router: classifies each question before any work happens,
so different question types can be handled differently instead of every
question being forced through the SQL-lookup pipeline regardless of fit.

Four categories:
  - lookup:               A direct factual question, answerable with a query.
  - analysis:              A comparative/aggregate question needing multiple
                           facts combined. Routed to the same SQL pipeline as
                           lookup for now — Slice 4 adds real statistical
                           tools (cohorts, significance, anomalies) that this
                           category will route to instead. The classification
                           already exists and is tested; giving it its own
                           handler later is additive, not a rewrite.
  - forecast:              A question about future/predicted values. No
                           forecasting tool and no time-series data exist yet
                           (Slice 4 / Slice 7), so this routes to an honest
                           "not supported yet" response instead of letting
                           the SQL agent attempt something it has no way to
                           do correctly.
  - needs_clarification:   The question is too ambiguous to answer as asked.
                           Routed to a node that asks a clarifying question
                           back, instead of guessing and confidently
                           answering the wrong thing.

Uses the LLM's structured-output feature (a Pydantic schema) rather than a
free-text prompt parsed by hand, specifically so the result is always one of
exactly four valid values — free-text classification means guarding against
the model inventing a fifth category or wrapping its answer in prose.
"""

from __future__ import annotations

from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from src.agent.llm_provider import get_llm

ROUTER_SYSTEM_PROMPT = """You are the routing layer for a video game market analytics agent. \
Classify the user's question into exactly one category:

- lookup: A direct factual question answerable by querying the games catalog for a \
specific value, ranking, or filtered list. Example: "Which game has the most owners?"

- analysis: A comparative, aggregate, or multi-part question that combines or compares \
data across groups. Example: "How does the average price of Action games compare to \
free-to-play games?"

- forecast: A question about future or predicted values — trends going forward, \
projections, "will X happen". Example: "How many players will this game have next month?" \
This system has no forecasting capability yet, so classify honestly even though it can't \
be answered.

- needs_clarification: The question is too vague or ambiguous to answer meaningfully as \
asked — it's missing a key detail (which game, what metric, what time period) or uses a \
subjective term ("best", "good") without defining it. Example: "Is this game good?"

If needs_clarification, write ONE short, specific question that would resolve the \
ambiguity. Otherwise leave clarifying_question empty.
"""


class RouteDecision(BaseModel):
    category: Literal["lookup", "analysis", "forecast", "needs_clarification"]
    clarifying_question: str = Field(
        default="",
        description=(
            "A short question to ask the user, populated only when "
            "category is needs_clarification."
        ),
    )


def classify_question(question: str) -> RouteDecision:
    router_llm = get_llm().with_structured_output(RouteDecision)
    return router_llm.invoke(
        [SystemMessage(content=ROUTER_SYSTEM_PROMPT), HumanMessage(content=question)]
    )
