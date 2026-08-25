"""The agent's forecast tool. Bound only for `forecast`-routed questions
(see src/agent/graph.py's `_tools_for_route`), same pattern as run_stats
being gated to `analysis`.

Same split as sql_tool.py/stats_tool.py: `execute_run_forecast` is the real
implementation, called directly by the graph's execute_tools node;
`run_forecast` (the @tool-decorated wrapper) exists only to hand the LLM a
schema.

The honesty constraint this tool is built around: `player_counts` (Slice 7)
is a genuinely young time series — as of this tool's introduction it holds
exactly ONE snapshot timestamp for the whole catalog, because the GitHub
Actions poller that accumulates more has only just started running. A
"forecast" fit to one point, or to a couple of points a few hours apart and
then projected a year out, is not a real forecast — it's a number shaped
like one. So this tool always checks how much history actually exists
before fitting anything, and returns a structured "not enough history yet"
result instead of fabricating a projection when there isn't enough — no
route-level block, no separate "not supported" terminal node needed
(compare to the Slice 3-8 `forecast_not_supported` node this replaces): the
tool itself degrades honestly, and self-upgrades to a real linear-trend
projection the moment ≥2 snapshots exist, with no further code changes.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from langchain_core.tools import tool
from scipy import stats as scipy_stats

from src.config import settings
from src.db.connection import get_read_only_connection, run_guarded_query


def execute_run_forecast(query: str, horizon_days: int) -> dict:
    conn = get_read_only_connection(settings.duckdb_abs_path)
    try:
        columns, rows = run_guarded_query(conn, query, settings.sql_max_rows)
    finally:
        conn.close()
    return _forecast(columns, rows, horizon_days)


def _forecast(columns: list[str], rows: list[list], horizon_days: int) -> dict:
    if len(columns) != 2:
        raise ValueError(
            "forecast mode requires a query returning exactly two columns: a "
            f"timestamp and a numeric value, one row per historical snapshot. Got "
            f"{len(columns)}: {columns}."
        )
    if horizon_days <= 0:
        raise ValueError(f"horizon_days must be positive, got {horizon_days}.")

    points: list[tuple[datetime, float]] = [
        (ts, float(value)) for ts, value in rows if ts is not None and value is not None
    ]
    if not points:
        raise ValueError("Query returned no non-null (timestamp, value) rows to forecast from.")
    points.sort(key=lambda p: p[0])

    distinct_timestamps = sorted({ts for ts, _ in points})
    n_snapshots = len(distinct_timestamps)
    earliest, latest = distinct_timestamps[0], distinct_timestamps[-1]

    if n_snapshots < 2:
        return {
            "mode": "forecast",
            "insufficient_history": True,
            "n_snapshots": n_snapshots,
            "earliest_snapshot": earliest.isoformat(),
            "message": (
                f"Only {n_snapshots} snapshot of player-count history exists for this "
                "game so far — at least 2 are needed to fit any trend. Live player "
                "counts are polled automatically on a schedule, so this will start "
                "working on its own once a second snapshot has been collected; it "
                "cannot be answered honestly right now."
            ),
        }

    x = [(ts - earliest).total_seconds() for ts, _ in points]
    y = [value for _, value in points]
    fit = scipy_stats.linregress(x, y)

    observed_span_days = max((latest - earliest).total_seconds() / 86400, 1e-9)
    target_ts = latest + timedelta(days=horizon_days)
    x_target = (target_ts - earliest).total_seconds()
    projected = max(0.0, fit.slope * x_target + fit.intercept)

    # Extrapolating further ahead than the span actually observed is exactly
    # where a linear fit stops being trustworthy — flag it rather than
    # present a confident-looking number. Same idea with too few points: a
    # line through 2-4 points captures noise as easily as trend.
    low_confidence_reasons = []
    if horizon_days > observed_span_days:
        low_confidence_reasons.append(
            f"projecting {horizon_days:.0f} day(s) ahead from only "
            f"{observed_span_days:.2f} day(s) of observed history"
        )
    if n_snapshots < 5:
        low_confidence_reasons.append(f"only {n_snapshots} snapshots collected so far")

    return {
        "mode": "forecast",
        "insufficient_history": False,
        "n_snapshots": n_snapshots,
        "earliest_snapshot": earliest.isoformat(),
        "latest_snapshot": latest.isoformat(),
        "observed_span_days": round(observed_span_days, 3),
        "horizon_days": horizon_days,
        "projected_date": target_ts.isoformat(),
        "projected_value": round(projected, 1),
        "slope_per_day": round(fit.slope * 86400, 3),
        "r_squared": round(fit.rvalue**2, 3),
        "low_confidence": bool(low_confidence_reasons),
        "low_confidence_reasons": low_confidence_reasons,
    }


@tool
def run_forecast(query: str, horizon_days: int) -> dict:
    """Project a game's future live player count from its real historical
    player-count time series via linear regression. Use this whenever the
    question asks about a future/predicted player count.

    The query MUST return exactly two columns, one row per historical
    snapshot: a timestamp column and the numeric player-count value, e.g.:
      SELECT polled_at, player_count FROM player_counts
      WHERE appid = (SELECT appid FROM games WHERE name ILIKE '%portal 2%')
      ORDER BY polled_at

    horizon_days: how many days into the future to project, inferred from
    the question's phrasing (tomorrow=1, next week=7, next month=30, next
    year=365, etc.).

    If fewer than 2 real snapshots exist yet for this game, the result will
    say so plainly (insufficient_history=true) instead of a fabricated
    number — report that honestly rather than making up a projection.
    When a projection IS returned, it also reports how much history it's
    based on (n_snapshots, observed_span_days) and whether it should be
    treated as low-confidence — always mention that in your answer rather
    than stating the projected number with unwarranted certainty.
    """
    return execute_run_forecast(query, horizon_days)
