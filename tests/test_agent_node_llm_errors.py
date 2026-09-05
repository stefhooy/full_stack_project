"""Tests for agent_node's own error handling (src/agent/graph.py) -- a
different failure class from test_graph_tool_errors.py's: those tests cover
a tool call that ran and failed (bad SQL), this covers the model call
itself failing to produce a usable message at all. Confirmed for real
against the live Groq provider, not hypothesized: `groq.BadRequestError:
Failed to parse tool call arguments as JSON` and separately `Tool choice is
none, but model called a tool` both crashed run_agent() end to end before
this handling existed, never reaching the self-correction loop. Mocks
get_llm() rather than hitting a real provider, matching this project's
`live`-marked-and-excluded-by-default convention for actual network/LLM
calls.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agent import graph as graph_module
from src.agent.graph import agent_node
from src.config import settings


@pytest.fixture(autouse=True)
def _skip_the_real_retry_backoff(monkeypatch):
    # agent_node sleeps settings.agent_retry_backoff_seconds (a real few
    # seconds, Slice 44) before its retry, so a rate-limit window has an
    # actual chance to clear in production. These tests exercise the real
    # code path, not a real rate limit, so there's nothing to wait for.
    monkeypatch.setattr(graph_module.time, "sleep", lambda seconds: None)


class _FailingModel:
    def invoke(self, messages):
        raise RuntimeError("simulated provider failure")


class _RecoveringModel:
    """bind_tools() -> a model that always fails; the bare llm (no tools
    bound) succeeds -- exercises the "one retry without tools" recovery
    path."""

    def bind_tools(self, tools):
        return _FailingModel()

    def invoke(self, messages):
        return AIMessage(content="a real plain-text answer")


class _AlwaysFailingModel:
    """Fails both with and without tools bound -- exercises the fully
    degraded fallback path."""

    def bind_tools(self, tools):
        return _FailingModel()

    def invoke(self, messages):
        raise RuntimeError("simulated provider failure")


def _state(*, attempts: int) -> dict:
    return {
        "messages": [HumanMessage(content="How many players will X have next month?")],
        "attempts": attempts,
        "tool_errors": 0,
        "route": "forecast",
    }


def test_model_invoke_failure_recovers_via_retry_without_tools(monkeypatch):
    monkeypatch.setattr(graph_module, "get_llm", lambda: _RecoveringModel())
    update = agent_node(_state(attempts=0))
    assert update["attempts"] == 1
    assert update["tool_errors"] == 1
    assert update["messages"][0].content == "a real plain-text answer"


def test_model_invoke_failure_degrades_honestly_when_the_retry_also_fails(monkeypatch):
    monkeypatch.setattr(graph_module, "get_llm", lambda: _AlwaysFailingModel())
    update = agent_node(_state(attempts=0))
    assert update["attempts"] == 1
    assert update["tool_errors"] == 1
    content = update["messages"][0].content
    assert "error" in content.lower()
    assert not update["messages"][0].tool_calls


def test_a_clean_model_call_never_touches_attempts_or_tool_errors(monkeypatch):
    class _CleanModel:
        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            return AIMessage(content="fine, no error at all")

    monkeypatch.setattr(graph_module, "get_llm", lambda: _CleanModel())
    update = agent_node(_state(attempts=0))
    assert "attempts" not in update
    assert "tool_errors" not in update
    assert update["messages"][0].content == "fine, no error at all"


def test_once_attempts_hits_the_cap_no_tools_are_bound_so_a_failure_cant_recur(monkeypatch):
    # If attempts is already at the cap, agent_node calls the bare llm
    # directly (no bind_tools), so this exercises the plain top-level
    # try/except succeeding on the very first call.
    class _BareModelThatWorks:
        def invoke(self, messages):
            return AIMessage(content="final answer, no more retries possible")

    monkeypatch.setattr(graph_module, "get_llm", lambda: _BareModelThatWorks())
    update = agent_node(_state(attempts=settings.sql_max_retries))
    assert "attempts" not in update
    assert update["messages"][0].content == "final answer, no more retries possible"
