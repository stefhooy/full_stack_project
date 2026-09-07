"""Tests for run_evals()'s per-question failure isolation (DOCEXP.md's
Slice 56 entry): a real quota-exhaustion crash mid-suite discarded every
question's already-completed real result, because nothing caught it.
Mocks run_agent/judge_answer entirely -- no real Groq calls needed to
verify this, matching this project's `live`-exclusion convention.
"""

from __future__ import annotations

import pytest

from src.agent.graph import AgentResult
from src.evals import run_evals as run_evals_module
from src.evals.checks import CheckResult, route_is
from src.evals.golden_questions import GoldenQuestion
from src.evals.judge import JudgeVerdict


def _fake_agent_result(**overrides) -> AgentResult:
    defaults = dict(
        answer="a real answer",
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
        estimated_cost_usd=0.0001,
    )
    defaults.update(overrides)
    return AgentResult(**defaults)


def _fake_questions(n: int) -> list[GoldenQuestion]:
    return [
        GoldenQuestion(
            id=f"q{i}",
            question=f"question {i}",
            expected_route="lookup",
            check=route_is("lookup"),
            reference_facts=f"reference {i}",
        )
        for i in range(n)
    ]


@pytest.fixture(autouse=True)
def _no_real_spacing_delay(monkeypatch):
    monkeypatch.setattr(run_evals_module.time, "sleep", lambda seconds: None)


def test_a_failing_agent_call_is_recorded_as_a_failure_not_a_crash(monkeypatch):
    monkeypatch.setattr(run_evals_module, "build_golden_questions", lambda: _fake_questions(3))

    def _flaky_run_agent(question: str) -> AgentResult:
        if question == "question 1":
            raise RuntimeError("simulated real failure, e.g. a quota exhaustion")
        return _fake_agent_result()

    monkeypatch.setattr(run_evals_module, "run_agent", _flaky_run_agent)
    monkeypatch.setattr(run_evals_module, "_call_with_retry", lambda fn, *a: fn(*a))

    results = run_evals_module.run_evals(use_judge=False)

    assert len(results) == 3, "one question failing must not stop the other two from running"
    assert results[0].passed
    assert not results[1].passed
    assert results[1].agent_result is None
    assert "agent call failed" in results[1].check_result.detail
    assert results[2].passed


def test_a_failing_judge_call_keeps_the_real_agent_result_and_check(monkeypatch):
    monkeypatch.setattr(run_evals_module, "build_golden_questions", lambda: _fake_questions(1))
    monkeypatch.setattr(run_evals_module, "run_agent", lambda q: _fake_agent_result())
    monkeypatch.setattr(run_evals_module, "_call_with_retry", lambda fn, *a: fn(*a))

    def _failing_judge(*args: object) -> JudgeVerdict:
        raise RuntimeError("simulated real failure, e.g. a quota exhaustion")

    monkeypatch.setattr(run_evals_module, "judge_answer", _failing_judge)

    results = run_evals_module.run_evals(use_judge=True)

    assert len(results) == 1
    assert results[0].passed  # the real check result must survive the judge failure
    assert results[0].judge_verdict is None
    assert results[0].agent_result is not None
    assert results[0].agent_result.answer == "a real answer"


def test_print_report_does_not_crash_on_a_totally_failed_question(monkeypatch, capsys):
    monkeypatch.setattr(run_evals_module, "build_golden_questions", lambda: _fake_questions(2))

    def _flaky_run_agent(question: str) -> AgentResult:
        if question == "question 0":
            raise RuntimeError("simulated failure")
        return _fake_agent_result()

    monkeypatch.setattr(run_evals_module, "run_agent", _flaky_run_agent)
    monkeypatch.setattr(run_evals_module, "_call_with_retry", lambda fn, *a: fn(*a))

    results = run_evals_module.run_evals(use_judge=False)
    all_passed = run_evals_module.print_report(results)  # must not raise

    assert all_passed is False
    out = capsys.readouterr().out
    assert "route accuracy:        1/2" in out  # only q1 has a real route to check
    assert "deterministic checks:   1/2" in out


def test_a_check_result_is_synthesized_from_a_real_check_result_type(monkeypatch):
    # Sanity: the synthetic failure result must be a real CheckResult, not
    # a loosely-typed stand-in -- print_report relies on .detail existing.
    def _always_fails(question: str) -> AgentResult:
        raise RuntimeError("boom")

    monkeypatch.setattr(run_evals_module, "build_golden_questions", lambda: _fake_questions(1))
    monkeypatch.setattr(run_evals_module, "run_agent", _always_fails)
    monkeypatch.setattr(run_evals_module, "_call_with_retry", lambda fn, *a: fn(*a))

    results = run_evals_module.run_evals(use_judge=False)
    assert isinstance(results[0].check_result, CheckResult)
    assert results[0].check_result.passed is False
