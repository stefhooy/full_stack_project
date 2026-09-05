"""Unit tests for RunStats (src/api/run_stats.py), the /health self-
correction and usage aggregator. Zero I/O, zero LLM calls -- pure
arithmetic over AgentResult fields -- which is exactly why this had no
excuse to sit at 0% coverage: this is the class of "the metric-computing
code has a bug and nobody would know" risk Slice 30's eval-check saga
already proved this project isn't immune to, just in a different module.
"""

from __future__ import annotations

from src.agent.graph import AgentResult
from src.api.run_stats import RunStats
from src.config import settings


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


def test_fresh_stats_report_empty_shape_not_a_division_by_zero():
    stats = RunStats()
    assert stats.as_dict() == {
        "total_runs": 0,
        "runs_with_tool_error": 0,
        "self_correction_rate": None,
        "recovered_after_error_rate": None,
    }
    assert stats.usage_as_dict() == {
        "total_tokens": 0,
        "avg_tokens_per_question": None,
        "total_cost_usd": 0.0,
        "avg_cost_per_question_usd": None,
    }


def test_a_clean_run_counts_toward_total_but_not_tool_error():
    stats = RunStats()
    stats.record(_result(tool_errors=0, attempts=1))
    d = stats.as_dict()
    assert d["total_runs"] == 1
    assert d["runs_with_tool_error"] == 0
    assert d["self_correction_rate"] == 0.0
    assert d["recovered_after_error_rate"] is None  # no errored runs to compute a rate over


def test_a_recovered_run_counts_as_tool_error_but_not_hit_the_cap():
    stats = RunStats()
    # Errored, but didn't exhaust the retry budget -- self-correction worked.
    stats.record(_result(tool_errors=1, attempts=settings.sql_max_retries - 1))
    d = stats.as_dict()
    assert d["runs_with_tool_error"] == 1
    assert d["self_correction_rate"] == 1.0
    assert d["recovered_after_error_rate"] == 1.0  # the one errored run, fully recovered


def test_a_run_that_hits_the_retry_cap_is_not_counted_as_recovered():
    stats = RunStats()
    stats.record(_result(tool_errors=1, attempts=settings.sql_max_retries))
    d = stats.as_dict()
    assert d["runs_with_tool_error"] == 1
    assert d["recovered_after_error_rate"] == 0.0  # errored AND exhausted the retry budget


def test_recovered_rate_is_the_real_intersection_not_two_independent_counts():
    # One recovered, one that hit the cap -- recovered_after_error_rate
    # must be exactly 0.5, not something that could go negative from
    # subtracting two independently-tracked counters (the docstring's own
    # stated reason for tracking the intersection directly).
    stats = RunStats()
    stats.record(_result(tool_errors=1, attempts=settings.sql_max_retries - 1))
    stats.record(_result(tool_errors=1, attempts=settings.sql_max_retries))
    d = stats.as_dict()
    assert d["runs_with_tool_error"] == 2
    assert d["recovered_after_error_rate"] == 0.5


def test_a_long_but_error_free_chain_that_happens_to_hit_the_cap_is_not_a_tool_error():
    # attempts >= cap with tool_errors == 0 must never be misclassified as
    # a self-correction failure -- the docstring names this exact edge
    # case as the reason the cap-hit counter is guarded by "had_error"
    # first, not just "attempts >= cap" alone.
    stats = RunStats()
    stats.record(_result(tool_errors=0, attempts=settings.sql_max_retries))
    d = stats.as_dict()
    assert d["runs_with_tool_error"] == 0
    assert d["self_correction_rate"] == 0.0


def test_usage_averages_tokens_over_every_run():
    stats = RunStats()
    stats.record(_result(total_tokens=100, estimated_cost_usd=0.01))
    stats.record(_result(total_tokens=300, estimated_cost_usd=0.03))
    d = stats.usage_as_dict()
    assert d["total_tokens"] == 400
    assert d["avg_tokens_per_question"] == 200.0


def test_cost_averages_only_over_runs_with_a_known_price_not_total_runs():
    # A run with estimated_cost_usd=None (an unpriced model) must not drag
    # the average down by being counted in the denominator -- the exact
    # bug the docstring says this separate counter exists to prevent.
    stats = RunStats()
    stats.record(_result(total_tokens=100, estimated_cost_usd=0.02))
    stats.record(_result(total_tokens=100, estimated_cost_usd=None))
    d = stats.usage_as_dict()
    assert d["total_cost_usd"] == 0.02
    assert d["avg_cost_per_question_usd"] == 0.02  # averaged over 1 known-cost run, not 2
