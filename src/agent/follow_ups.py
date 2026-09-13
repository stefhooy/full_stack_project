"""Deterministic, zero-LLM-cost follow-up question suggestions.

Generated purely from data the agent already computed for the current
answer (route, columns, rows, stats/forecast result) -- never a second
model call. A suggested follow-up is a nice-to-have UX affordance, not
a correctness concern, so it doesn't earn the same "worth a dedicated
Groq call" treatment the router's own classification gets. Computed
once inside _result_from_state() (src/agent/graph.py), so it's part of
what the semantic cache stores and replays on a cache hit too, just
like the answer text itself.

Kept in its own module (not graph.py) so it can be unit-tested as a
plain pure function, following checks.py's precedent in src/evals.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.agent.graph import AgentResult

MAX_SUGGESTIONS = 3


def _first_row_name(result: AgentResult) -> str | None:
    """Best-effort game name from the current answer's own result rows.
    Works for both the lookup and forecast routes: a forecast question's
    companion run_sql call (resolving the named game to an appid) already
    populates columns/rows the same way a plain lookup does."""
    if not result.rows or not result.columns:
        return None
    first_row = result.rows[0]
    if not first_row:
        return None
    try:
        idx = result.columns.index("name")
    except ValueError:
        idx = 0
    value = first_row[idx] if idx < len(first_row) else None
    return str(value) if value else None


def generate_follow_up_suggestions(result: AgentResult) -> list[str]:
    """Up to MAX_SUGGESTIONS standalone next questions, or an empty list
    if nothing specific enough was available to suggest (deliberately no
    generic filler fallback -- an empty list of chips is preferable to a
    suggestion that isn't really about this answer)."""
    suggestions: list[str] = []
    name = _first_row_name(result)

    if result.route == "lookup":
        if name:
            suggestions.append(f"How has {name}'s player count changed over time?")
            suggestions.append(f"How does {name} compare to similar games?")
    elif result.route == "analysis":
        stats = result.stats_result or {}
        mode = stats.get("mode")
        if mode == "compare_two_groups":
            group_a, group_b = stats.get("group_a"), stats.get("group_b")
            if group_a and group_b:
                suggestions.append(
                    f"How does that compare for a category besides {group_a} and {group_b}?"
                )
        elif mode == "outliers":
            suggestions.append("Are there similar outliers for a different metric?")
        elif mode == "describe":
            suggestions.append("How does that compare across genres?")
    elif result.route == "forecast":
        if name:
            suggestions.append(f"How has {name}'s player count trended so far?")
        suggestions.append("What about a different game?")

    return suggestions[:MAX_SUGGESTIONS]
