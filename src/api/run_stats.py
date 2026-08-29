"""In-memory aggregate stats over real (non-cached) agent runs: how often
the agent's self-correction loop actually gets exercised, how often it
still produces a real answer versus running out of retry budget, and real
cumulative token usage/cost. Surfaced via /health so these are real,
quotable numbers instead of something only visible per-request in logs
or, for cost, only visible by running the eval suite by hand (Slice 24's
`run_evals.py` instrumentation; this class is Slice 26's live-request
equivalent of the same measurement, sharing the same pricing source,
src/agent/pricing.py).

Same in-memory, single-process pattern as cache.py and rate_limit.py --
correct for this deployment (a single long-running process, see DOCEXP.md's
Slice 6 entry), would need a shared store to stay accurate across multiple
instances. Not solved speculatively before it's needed, same reasoning as
those two.

Two independent facts are tracked per run, not conflated into one:
  - `tool_errors > 0`: at least one tool call actually failed and had to be
    fed back to the model -- the real self-correction signal (see
    AgentState's `tool_errors` docstring in src/agent/graph.py for why this
    is a separate counter from `attempts`, which also counts legitimate
    multi-step tool use that never failed at all).
  - `attempts >= SQL_MAX_RETRIES`: the structural retry cap was hit
    (agent_node stops binding tools at all once this is true). In this
    system that almost always means repeated errors, but technically could
    also mean a long *successful* multi-step chain that happened to reach
    the same count -- named precisely rather than assumed identical to
    "self-correction failed."
"""

from __future__ import annotations

from dataclasses import dataclass

from src.agent.graph import AgentResult
from src.config import settings


@dataclass
class RunStats:
    total_runs: int = 0
    runs_with_tool_error: int = 0
    # Deliberately the intersection (tool_errors > 0 AND hit the cap), not a
    # second independent counter -- tracking it directly means it's always
    # a subset of runs_with_tool_error by construction, so "recovered" below
    # can never go negative from an edge case (a long but error-free chain
    # that happens to also hit the attempts cap) sneaking into the wrong
    # bucket.
    runs_with_tool_error_that_hit_the_attempts_cap: int = 0
    total_tokens: int = 0
    # Sum of only the runs with a known price (estimated_cost_usd is not
    # None) -- kept alongside a separate count of *how many* runs had a
    # known price, so an average never silently divides by the wrong
    # denominator if a future model swap ever leaves some runs unpriced.
    total_cost_usd: float = 0.0
    runs_with_known_cost: int = 0

    def record(self, result: AgentResult) -> None:
        self.total_runs += 1
        had_error = result.tool_errors > 0
        if had_error:
            self.runs_with_tool_error += 1
            if result.attempts >= settings.sql_max_retries:
                self.runs_with_tool_error_that_hit_the_attempts_cap += 1
        self.total_tokens += result.total_tokens
        if result.estimated_cost_usd is not None:
            self.total_cost_usd += result.estimated_cost_usd
            self.runs_with_known_cost += 1

    def usage_as_dict(self) -> dict:
        if self.total_runs == 0:
            return {
                "total_tokens": 0,
                "avg_tokens_per_question": None,
                "total_cost_usd": 0.0,
                "avg_cost_per_question_usd": None,
            }
        avg_cost = (
            self.total_cost_usd / self.runs_with_known_cost if self.runs_with_known_cost else None
        )
        return {
            "total_tokens": self.total_tokens,
            "avg_tokens_per_question": round(self.total_tokens / self.total_runs, 1),
            "total_cost_usd": round(self.total_cost_usd, 5),
            "avg_cost_per_question_usd": round(avg_cost, 5) if avg_cost is not None else None,
        }

    def as_dict(self) -> dict:
        if self.total_runs == 0:
            return {
                "total_runs": 0,
                "runs_with_tool_error": 0,
                "self_correction_rate": None,
                "recovered_after_error_rate": None,
            }
        # Of the runs that hit at least one error, how many still produced
        # a real answer without running out of retry budget -- the actual
        # "did self-correction work" number, not just "did it happen."
        recovered = self.runs_with_tool_error - self.runs_with_tool_error_that_hit_the_attempts_cap
        recovered_rate = (
            recovered / self.runs_with_tool_error if self.runs_with_tool_error else None
        )
        return {
            "total_runs": self.total_runs,
            "runs_with_tool_error": self.runs_with_tool_error,
            "self_correction_rate": round(self.runs_with_tool_error / self.total_runs, 3),
            "recovered_after_error_rate": (
                round(recovered_rate, 3) if recovered_rate is not None else None
            ),
        }
