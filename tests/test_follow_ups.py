"""Unit tests for generate_follow_up_suggestions (src/agent/follow_ups.py).
Pure, deterministic, zero-LLM-cost -- see that module's own docstring for
why this is a plain function instead of a second Groq call.
"""

from __future__ import annotations

from src.agent.follow_ups import MAX_SUGGESTIONS, generate_follow_up_suggestions
from src.agent.graph import AgentResult


def _result(**overrides) -> AgentResult:
    defaults = dict(
        answer="",
        sql=None,
        columns=None,
        rows=None,
        stats_query=None,
        stats_result=None,
        forecast_query=None,
        forecast_result=None,
        retrieved_chunk_ids=None,
        route="lookup",
        chart_spec=None,
        attempts=1,
        tool_errors=0,
        total_tokens=100,
        estimated_cost_usd=0.001,
    )
    defaults.update(overrides)
    return AgentResult(**defaults)


def test_lookup_with_a_named_game_suggests_history_and_comparison():
    result = _result(
        route="lookup",
        columns=["name", "peak_ccu"],
        rows=[["Counter-Strike: Global Offensive", 1013936]],
    )
    suggestions = generate_follow_up_suggestions(result)
    assert any("Counter-Strike: Global Offensive" in s for s in suggestions)
    assert len(suggestions) <= MAX_SUGGESTIONS


def test_lookup_with_no_rows_suggests_nothing():
    result = _result(route="lookup", columns=None, rows=None)
    assert generate_follow_up_suggestions(result) == []


def test_analysis_compare_two_groups_names_both_real_groups():
    result = _result(
        route="analysis",
        stats_result={"mode": "compare_two_groups", "group_a": "Action", "group_b": "Indie"},
    )
    suggestions = generate_follow_up_suggestions(result)
    assert len(suggestions) == 1
    assert "Action" in suggestions[0]
    assert "Indie" in suggestions[0]


def test_analysis_outliers_gets_a_generic_but_relevant_suggestion():
    result = _result(route="analysis", stats_result={"mode": "outliers", "outliers": []})
    suggestions = generate_follow_up_suggestions(result)
    assert suggestions == ["Are there similar outliers for a different metric?"]


def test_analysis_describe_gets_a_generic_but_relevant_suggestion():
    result = _result(route="analysis", stats_result={"mode": "describe"})
    suggestions = generate_follow_up_suggestions(result)
    assert suggestions == ["How does that compare across genres?"]


def test_forecast_with_a_named_game_suggests_history_and_a_different_game():
    result = _result(
        route="forecast",
        columns=["name", "appid"],
        rows=[["Counter-Strike: Global Offensive", 730]],
        forecast_result={"mode": "forecast", "insufficient_history": False},
    )
    suggestions = generate_follow_up_suggestions(result)
    assert any("Counter-Strike: Global Offensive" in s for s in suggestions)
    assert "What about a different game?" in suggestions


def test_needs_clarification_never_gets_suggestions():
    # Suggesting a *next* question doesn't make sense before the current
    # one is even resolved.
    result = _result(route="needs_clarification")
    assert generate_follow_up_suggestions(result) == []


def test_never_returns_more_than_the_max():
    result = _result(
        route="lookup",
        columns=["name"],
        rows=[["Some Game"]],
    )
    assert len(generate_follow_up_suggestions(result)) <= MAX_SUGGESTIONS
