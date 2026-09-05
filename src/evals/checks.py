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


def _normalize_whitespace(text: str) -> str:
    # Real, observed behavior (Slice 44): the model sometimes renders a
    # brand name using a Unicode narrow-no-break-space character between
    # words rather than a plain ASCII space (e.g. a stylized rendering of
    # "EA SPORTS FC 24"), which a plain substring check misses even
    # though the answer is factually correct. re's \s matches these
    # Unicode space variants (confirmed empirically), a literal `in`
    # check doesn't.
    return re.sub(r"\s+", " ", text)


def contains_text(expected_substring: str) -> Check:
    def check(result: AgentResult) -> CheckResult:
        answer_norm = _normalize_whitespace(result.answer).lower()
        expected_norm = _normalize_whitespace(expected_substring).lower()
        found = expected_norm in answer_norm
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


def forecast_has_real_projection() -> Check:
    """For a forecast question where enough real history exists: the tool
    must have actually run and produced a real (not insufficient-history)
    projection, not the model answering from schema-level guesswork alone
    (a real, previously-observed failure mode — see DOCEXP.md's Slice 32
    entry)."""

    def check(result: AgentResult) -> CheckResult:
        fr = result.forecast_result
        ok = fr is not None and fr.get("insufficient_history") is False
        return CheckResult(
            ok, f"expected a real forecast_result with insufficient_history=False, got {fr!r}"
        )

    return check


def forecast_reports_insufficient_history() -> Check:
    """For a forecast question about a game with too little (or no) real
    history: the tool must honestly report that, not fabricate a number.
    This is the tool's own core design promise (src/tools/forecast_tool.py),
    checked here as a real regression test of it, not just asserted in a
    docstring."""

    def check(result: AgentResult) -> CheckResult:
        fr = result.forecast_result
        ok = fr is not None and fr.get("insufficient_history") is True
        return CheckResult(
            ok, f"expected forecast_result with insufficient_history=True, got {fr!r}"
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
