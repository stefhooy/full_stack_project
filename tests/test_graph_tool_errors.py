"""Tests for execute_tools_node's two counters (src/agent/graph.py): `attempts`
counts every tool-call round trip, `tool_errors` counts only the ones that
actually failed. The whole point of having two separate counters is that a
legitimate multi-step question (two successful tool calls) must not look
identical to a real self-correction retry (one failed, one recovered) --
these tests exercise both real DuckDB fixture paths, not a mock of
execute_run_sql, same "real fixture over mocking this project's own layer"
approach as test_catalog.py/test_genre_stats.py.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from src.agent.graph import execute_tools_node
from src.config import settings


@pytest.fixture(autouse=True)
def _point_settings_at_test_db(games_db, monkeypatch):
    monkeypatch.setattr(settings, "duckdb_path", games_db)


def _state(*, attempts: int, tool_calls: list[dict]) -> dict:
    return {
        "messages": [AIMessage(content="", tool_calls=tool_calls)],
        "attempts": attempts,
        "tool_errors": 0,
    }


def test_a_successful_call_increments_attempts_but_not_tool_errors():
    state = _state(
        attempts=0,
        tool_calls=[
            {"name": "run_sql", "args": {"query": "SELECT COUNT(*) FROM games"}, "id": "c1"}
        ],
    )
    update = execute_tools_node(state)
    assert update["attempts"] == 1
    assert update["tool_errors"] == 0
    assert not update["messages"][0].content.startswith("Error:")


def test_a_failing_call_increments_both_attempts_and_tool_errors():
    state = _state(
        attempts=0,
        tool_calls=[{"name": "run_sql", "args": {"query": "DROP TABLE games"}, "id": "c1"}],
    )
    update = execute_tools_node(state)
    assert update["attempts"] == 1
    assert update["tool_errors"] == 1
    assert update["messages"][0].content.startswith("Error:")


def test_two_legitimate_successful_calls_never_touch_tool_errors():
    """The exact distinction this feature exists for: a question needing
    two real tool calls must not look like a retry."""
    state = _state(
        attempts=0,
        tool_calls=[
            {"name": "run_sql", "args": {"query": "SELECT COUNT(*) FROM games"}, "id": "c1"},
            {"name": "run_sql", "args": {"query": "SELECT name FROM games LIMIT 1"}, "id": "c2"},
        ],
    )
    update = execute_tools_node(state)
    assert update["attempts"] == 2
    assert update["tool_errors"] == 0


def test_retry_limit_message_appears_once_the_attempts_cap_is_reached():
    # Start one below the cap so this single failing call pushes attempts
    # to exactly settings.sql_max_retries.
    state = _state(
        attempts=settings.sql_max_retries - 1,
        tool_calls=[{"name": "run_sql", "args": {"query": "DROP TABLE games"}, "id": "c1"}],
    )
    update = execute_tools_node(state)
    assert update["attempts"] == settings.sql_max_retries
    assert update["tool_errors"] == 1
    assert "Retry limit" in update["messages"][0].content
