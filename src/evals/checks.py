"""Reusable, composable deterministic check builders for golden questions.

Each builder returns a function AgentResult -> CheckResult. Kept separate
from golden_questions.py so the check *logic* (how do we decide pass/fail)
is easy to scan independently of the *content* (which questions, which
reference facts) — the same separation of concerns as prompts.py vs.
schema_corpus.py elsewhere in this codebase.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from src.agent.graph import AgentResult


@dataclass
class CheckResult:
    passed: bool
    detail: str


Check = Callable[[AgentResult], CheckResult]


def _numbers_in(text: str) -> list[float]:
    return [float(m.replace(",", "")) for m in re.findall(r"-?\d[\d,]*\.?\d*", text)]


def contains_number(expected: float, tolerance: float = 0.05, rel: bool = True) -> Check:
    """Pass if any number-looking substring in the answer is within
    `tolerance` of `expected`. `rel=True` treats tolerance as a fraction of
    `expected` (5% by default); `rel=False` treats it as an absolute gap —
    use absolute for small/zero expected values where a relative tolerance
    would be meaninglessly tight."""

    def check(result: AgentResult) -> CheckResult:
        found = _numbers_in(result.answer)
        gap = tolerance * abs(expected) if rel else tolerance
        for n in found:
            if abs(n - expected) <= max(gap, 1e-9):
                return CheckResult(True, f"found {n} in answer, matches expected {expected}")
        return CheckResult(
            False, f"expected a number near {expected} in the answer; found {found}"
        )

    return check


def contains_text(expected_substring: str) -> Check:
    def check(result: AgentResult) -> CheckResult:
        found = expected_substring.lower() in result.answer.lower()
        return CheckResult(
            found,
            f"expected {expected_substring!r} in answer (found={found}): {result.answer[:120]!r}",
        )

    return check


def route_is(expected_route: str) -> Check:
    def check(result: AgentResult) -> CheckResult:
        return CheckResult(
            result.route == expected_route,
            f"expected route={expected_route!r}, got {result.route!r}",
        )

    return check


def no_data_fabricated() -> Check:
    """For forecast/clarification questions: the agent must not have run a
    query or produced a stats result — there's nothing it should be
    computing on those paths."""

    def check(result: AgentResult) -> CheckResult:
        clean = result.sql is None and result.stats_result is None
        return CheckResult(
            clean, f"expected no sql/stats_result, got sql={result.sql!r}, "
            f"stats_result={'present' if result.stats_result else None}"
        )

    return check


def all_of(*checks: Check) -> Check:
    def check(result: AgentResult) -> CheckResult:
        results = [c(result) for c in checks]
        passed = all(r.passed for r in results)
        detail = "; ".join(r.detail for r in results)
        return CheckResult(passed, detail)

    return check
