"""Tests for router_node's own error handling (src/agent/graph.py) -- the
item-3 follow-up to Slice 42's agent_node fix. classify_question (the
router's own LLM call, src/agent/router.py) had zero error handling until
this slice: a single failure there crashed the whole request up to the
API's blanket 503 catch-all, instead of the retry-then-degrade-honestly
behavior agent_node already gets for its own model call. Mocks
classify_question rather than hitting a real provider, matching this
project's `live`-marked-and-excluded-by-default convention.
"""

from __future__ import annotations

import httpx
import pytest
from groq import RateLimitError

from src.agent import graph as graph_module
from src.agent.graph import GROQ_RATE_LIMIT_MESSAGE, router_node
from src.agent.router import RouteDecision


@pytest.fixture(autouse=True)
def _skip_the_real_retry_backoff(monkeypatch):
    # router_node sleeps settings.agent_retry_backoff_seconds before its
    # retry, same reasoning as agent_node's own test file -- nothing to
    # actually wait for against a mocked classify_question.
    monkeypatch.setattr(graph_module.time, "sleep", lambda seconds: None)


def _fake_rate_limit_error() -> RateLimitError:
    # groq.RateLimitError requires a real httpx.Response -- a bare
    # RuntimeError wouldn't exercise the isinstance check this file's
    # RateLimitError-specific tests are actually verifying.
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(429, request=request)
    return RateLimitError("simulated real Groq rate limit", response=response, body=None)


def _state() -> dict:
    return {"question": "How many players will X have next month?"}


def test_classify_question_failure_recovers_via_retry(monkeypatch):
    calls = {"n": 0}

    def flaky(question: str) -> RouteDecision:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated provider failure")
        return RouteDecision(category="forecast", clarifying_question="")

    monkeypatch.setattr(graph_module, "classify_question", flaky)
    update = router_node(_state())
    assert update["route"] == "forecast"
    assert calls["n"] == 2


def test_classify_question_failure_degrades_honestly_when_the_retry_also_fails(monkeypatch):
    def always_fails(question: str) -> RouteDecision:
        raise RuntimeError("simulated provider failure")

    monkeypatch.setattr(graph_module, "classify_question", always_fails)
    update = router_node(_state())
    assert update["route"] == "needs_clarification"
    assert update["clarifying_question"]
    assert "error" in update["clarifying_question"].lower()


def test_a_real_rate_limit_degrades_to_the_honest_quota_message(monkeypatch):
    # DOCEXP.md's Slice 57: a plain RuntimeError degrading to "try
    # rephrasing or ask again in a moment" is fine for a one-off hiccup,
    # but actively misleading when both the call and its retry failed on
    # a real groq.RateLimitError -- that's a genuine daily-quota
    # exhaustion, not something a rephrase or a few seconds fixes.
    def always_rate_limited(question: str) -> RouteDecision:
        raise _fake_rate_limit_error()

    monkeypatch.setattr(graph_module, "classify_question", always_rate_limited)
    update = router_node(_state())
    assert update["route"] == "needs_clarification"
    assert update["clarifying_question"] == GROQ_RATE_LIMIT_MESSAGE


def test_a_clean_classify_question_call_never_retries(monkeypatch):
    calls = {"n": 0}

    def clean(question: str) -> RouteDecision:
        calls["n"] += 1
        return RouteDecision(category="lookup", clarifying_question="")

    monkeypatch.setattr(graph_module, "classify_question", clean)
    update = router_node(_state())
    assert update["route"] == "lookup"
    assert update["clarifying_question"] is None
    assert calls["n"] == 1


def test_a_real_needs_clarification_decision_still_passes_through_normally(monkeypatch):
    def clean(question: str) -> RouteDecision:
        return RouteDecision(category="needs_clarification", clarifying_question="Which game?")

    monkeypatch.setattr(graph_module, "classify_question", clean)
    update = router_node(_state())
    assert update["route"] == "needs_clarification"
    assert update["clarifying_question"] == "Which game?"
