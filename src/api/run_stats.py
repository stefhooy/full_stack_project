"""In-memory aggregate stats over real (non-cached) agent runs: how often
the agent's self-correction loop actually gets exercised, and how often it
still produces a real answer versus running out of retry budget. Surfaced
via /health so this is a real, quotable number instead of something only
visible per-request in logs.

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

    def record(self, result: AgentResult) -> None:
        self.total_runs += 1
        had_error = result.tool_errors > 0
        if had_error:
            self.runs_with_tool_error += 1
            if result.attempts >= settings.sql_max_retries:
                self.runs_with_tool_error_that_hit_the_attempts_cap += 1

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
