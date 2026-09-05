"""Eval harness runner. Runs every golden question through the real agent
(full graph, real DB, real LLM), checks it two ways, and prints a report.

Usage:
    python -m src.evals.run_evals            # deterministic checks + LLM judge
    python -m src.evals.run_evals --no-judge  # skip the judge (faster, no extra LLM calls)

Exit code is 0 only if every question's route AND deterministic check
passed — that's the part meant to gate CI later (Slice 6+). The judge score
is printed for visibility but does NOT affect the exit code: LLM judges
have their own noise, and treating a qualitative 1-5 score as a hard
pass/fail gate would make the regression check flaky in a way a
deterministic check checking real facts against the live DB isn't.
"""

from __future__ import annotations

import argparse
import sys
import time

# LLM output can contain arbitrary Unicode (smart quotes, non-breaking
# hyphens, etc.) that Windows' default console encoding (cp1252) can't
# represent — crashes the report mid-print otherwise. UTF-8 with
# replacement is the right fix here (this is a report to a terminal, not
# a place where losing an unencodable character silently matters).
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    # sys.stdout is typed as the abstract TextIO protocol, which doesn't
    # declare reconfigure() (only the concrete TextIOWrapper it actually is
    # at runtime does) -- a known typeshed gap, not a real type error.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
from collections.abc import Callable
from dataclasses import dataclass

from groq import RateLimitError
from langchain_core.callbacks import get_usage_metadata_callback

from src.agent.graph import AgentResult, run_agent
from src.agent.pricing import estimate_cost_usd
from src.evals.checks import CheckResult
from src.evals.golden_questions import GoldenQuestion, build_golden_questions
from src.evals.judge import JudgeVerdict, judge_answer

# Groq's free tier caps openai/gpt-oss-120b at 8000 tokens/minute (TPM) --
# confirmed for real (Slice 28) when the scheduled GitHub Actions run hit
# a genuine 429 mid-suite, not from external traffic but from this suite's
# own back-to-back questions (several use 3000-4700+ tokens each; two or
# three landing in the same rolling minute is enough to burst past 8000).
# Two mitigations, not one: a small proactive gap between questions
# (SPACING_SECONDS) to spread usage across the minute, and a real retry
# with backoff (_call_with_retry) as a safety net for whenever spacing
# alone isn't enough. Groq's own error message told us the wait needed
# was tiny (412.5ms) that one time, but a rolling-window limit can need up
# to the whole window to clear, so backoff is seconds, not milliseconds.
#
# Raised from 5.0 to 20.0 in Slice 44, when growing the golden set from 5
# to 15 questions (several of the new ones are 5000-8000+ tokens each,
# bigger on average than the original set) reproduced the exact same
# class of failure the comment above already describes: a real eval run
# came back 7/15 deterministic checks, most of the failures showing
# agent_node's own degraded fallback text and suspiciously small token
# counts, both signatures of a rate-limited call that never got to
# generate a real answer. 5s between questions was never really enough
# once the set includes several genuinely large questions back to back;
# 20s keeps any two heavy questions from landing in the same rolling
# TPM window in the first place, rather than leaning entirely on
# _call_with_retry to clean up after the fact.
SPACING_SECONDS = 20.0


def _call_with_retry[T](fn: Callable[..., T], *args: object, max_attempts: int = 3) -> T:
    """Takes fn and its args separately, not a zero-arg lambda closing over
    a loop variable -- avoids the late-binding-closure trap (and the lint
    rule for it) entirely rather than relying on remembering to invoke the
    lambda within the same iteration it's defined in."""
    for attempt in range(1, max_attempts + 1):
        try:
            return fn(*args)
        except RateLimitError:
            if attempt == max_attempts:
                raise
            time.sleep(15.0 * attempt)  # 15s, then 30s
    raise AssertionError("unreachable")  # loop always returns or raises


@dataclass
class EvalRunResult:
    golden: GoldenQuestion
    agent_result: AgentResult
    check_result: CheckResult
    judge_verdict: JudgeVerdict | None
    latency_seconds: float
    token_usage: dict
    """Only the real agent run's LLM calls (router + agent node, across any
    retries) -- the judge's own LLM call happens outside the tracked block
    on purpose, since it's eval-harness overhead a real /ask caller never
    pays for, not part of what answering this question actually costs."""
    estimated_cost_usd: float | None

    @property
    def passed(self) -> bool:
        return self.check_result.passed


def run_evals(use_judge: bool = True) -> list[EvalRunResult]:
    results = []
    for i, gq in enumerate(build_golden_questions()):
        if i > 0:
            # Proactive spacing, not just reactive retry -- see
            # SPACING_SECONDS' comment for why a fixed suite of questions
            # can burst a per-minute token cap on its own.
            time.sleep(SPACING_SECONDS)

        start = time.monotonic()
        with get_usage_metadata_callback() as cb:
            agent_result = _call_with_retry(run_agent, gq.question)
        latency = time.monotonic() - start
        check_result = gq.check(agent_result)
        judge_verdict = (
            _call_with_retry(
                judge_answer, gq.question, agent_result.answer, gq.reference_facts
            )
            if use_judge
            else None
        )
        cost = estimate_cost_usd(cb.usage_metadata)
        results.append(
            EvalRunResult(
                gq, agent_result, check_result, judge_verdict, latency, cb.usage_metadata, cost
            )
        )
    return results


def print_report(results: list[EvalRunResult]) -> bool:
    print(f"\n{'ID':32s} {'PASS':6s} {'JUDGE':7s} {'LATENCY':8s} {'TOKENS':8s} {'COST':9s}  DETAIL")
    print("-" * 100)
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        judge_str = f"{r.judge_verdict.score}/5" if r.judge_verdict else "-"
        total_tokens = sum(u.get("total_tokens", 0) for u in r.token_usage.values())
        cost_str = f"${r.estimated_cost_usd:.5f}" if r.estimated_cost_usd is not None else "?"
        print(
            f"{r.golden.id:32s} {status:6s} {judge_str:7s} "
            f"{r.latency_seconds:6.1f}s {total_tokens:8d} {cost_str:9s}  {r.check_result.detail}"
        )
        if r.judge_verdict:
            print(f"{'':32s} {'':6s} judge: {r.judge_verdict.rationale}")

    n = len(results)
    n_passed = sum(1 for r in results if r.passed)
    n_route_correct = sum(1 for r in results if r.agent_result.route == r.golden.expected_route)
    judged = [r.judge_verdict.score for r in results if r.judge_verdict]
    avg_judge = sum(judged) / len(judged) if judged else None
    costs = [r.estimated_cost_usd for r in results if r.estimated_cost_usd is not None]
    avg_cost = sum(costs) / len(costs) if costs else None
    avg_latency = sum(r.latency_seconds for r in results) / n if n else None

    print("-" * 100)
    print(f"route accuracy:        {n_route_correct}/{n}")
    print(f"deterministic checks:   {n_passed}/{n}")
    if avg_judge is not None:
        print(f"avg judge score:        {avg_judge:.1f}/5")
    if avg_latency is not None:
        print(
            f"avg /ask latency:       {avg_latency:.1f}s  "
            f"(n={n}, real full-graph runs, not a formal percentile)"
        )
    if avg_cost is not None:
        print(
            f"avg cost per question:  ${avg_cost:.5f}  "
            "(Groq on-demand list price, router+agent calls only)"
        )
    print()

    return n_passed == n


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the golden question eval suite.")
    parser.add_argument("--no-judge", action="store_true", help="Skip the LLM-as-judge pass.")
    args = parser.parse_args()

    results = run_evals(use_judge=not args.no_judge)
    all_passed = print_report(results)
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
