"""The agent's second tool: run_stats. Bound only for `analysis`-routed
questions (see src/agent/graph.py's agent_node), so `lookup` questions
still see just run_sql — a concrete example of the router actually gating
tool availability, not just labeling questions.

Same split as sql_tool.py: `execute_run_stats` is the real implementation,
called directly by the graph's execute_tools node; `run_stats` (the
@tool-decorated wrapper) exists only to hand the LLM a schema.

Three modes, chosen to cover what plain SQL aggregates genuinely can't do
well (DuckDB already has AVG/STDDEV/CORR/etc. built in — this tool isn't
duplicating those):
  - "describe":            summary stats for one numeric column.
  - "compare_two_groups":  a real Welch's t-test (via scipy) between two
                            groups, with a p-value — not just "which
                            average looked bigger", which is what the SQL
                            agent was doing (unreliably — see DOCEXP.md)
                            before this tool existed.
  - "outliers":             z-score based anomaly detection.

Every mode runs its query through the same guarded, read-only connection
as run_sql — this tool is not a way to bypass the SELECT-only/allowlist
guard, it's SQL-in, statistics-out.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

import numpy as np
from langchain_core.tools import tool
from scipy import stats as scipy_stats

from src.config import settings
from src.db.connection import get_read_only_connection, run_guarded_query


def execute_run_stats(query: str, mode: str, z_threshold: float = 2.5) -> dict:
    # Tool-call args arrive from the LLM's function-calling output, not from
    # trusted Python code — some providers (observed with Ollama) serialize
    # a float arg as a JSON string ("2.5") even though the schema declares
    # it numeric. Coerce here rather than trust the type that arrives.
    z_threshold = float(z_threshold)

    conn = get_read_only_connection(settings.duckdb_abs_path)
    try:
        columns, rows = run_guarded_query(conn, query, settings.sql_max_rows)
    finally:
        conn.close()

    if mode == "describe":
        return _describe(columns, rows)
    if mode == "compare_two_groups":
        return _compare_two_groups(columns, rows)
    if mode == "outliers":
        return _outliers(columns, rows, z_threshold)
    raise ValueError(
        f"Unknown stats mode: {mode!r}. Use describe, compare_two_groups, or outliers."
    )


def _describe(columns: list[str], rows: Sequence[Sequence[Any]]) -> dict:
    if len(columns) != 1:
        raise ValueError(
            f"describe mode requires a query returning exactly one numeric column, "
            f"got {len(columns)}: {columns}."
        )
    values = np.array([r[0] for r in rows if r[0] is not None], dtype=float)
    if values.size == 0:
        raise ValueError("Query returned no non-null values to describe.")
    return {
        "mode": "describe",
        "n": int(values.size),
        "mean": float(np.mean(values)),
        "median": float(np.median(values)),
        "stddev": float(np.std(values, ddof=1)) if values.size > 1 else 0.0,
        "min": float(np.min(values)),
        "max": float(np.max(values)),
        "p25": float(np.percentile(values, 25)),
        "p75": float(np.percentile(values, 75)),
    }


def _compare_two_groups(columns: list[str], rows: Sequence[Sequence[Any]]) -> dict:
    if len(columns) != 2:
        raise ValueError(
            "compare_two_groups mode requires a query returning exactly two columns: "
            f"a group label and a numeric value. Got {len(columns)}: {columns}."
        )
    groups: dict[str, list[float]] = {}
    for label, value in rows:
        if value is None:
            continue
        groups.setdefault(str(label), []).append(float(value))
    if len(groups) != 2:
        raise ValueError(
            "compare_two_groups mode requires exactly two distinct group labels in the "
            f"query result, found {len(groups)}: {sorted(groups)}."
        )
    (label_a, values_a), (label_b, values_b) = sorted(groups.items())
    a, b = np.array(values_a), np.array(values_b)
    if a.size < 2 or b.size < 2:
        raise ValueError("Each group needs at least 2 observations to run a t-test.")

    t_statistic, p_value = scipy_stats.ttest_ind(a, b, equal_var=False)  # Welch's t-test
    pooled_std = np.sqrt((a.var(ddof=1) + b.var(ddof=1)) / 2)
    cohens_d = float((a.mean() - b.mean()) / pooled_std) if pooled_std > 0 else 0.0

    return {
        "mode": "compare_two_groups",
        "group_a": label_a,
        "n_a": int(a.size),
        "mean_a": float(a.mean()),
        "group_b": label_b,
        "n_b": int(b.size),
        "mean_b": float(b.mean()),
        "mean_difference": float(a.mean() - b.mean()),
        "t_statistic": float(t_statistic),
        "p_value": float(p_value),
        "significant_at_0.05": bool(p_value < 0.05),
        "cohens_d": cohens_d,
    }


def _outliers(columns: list[str], rows: Sequence[Sequence[Any]], z_threshold: float) -> dict:
    if len(columns) != 2:
        raise ValueError(
            "outliers mode requires a query returning exactly two columns: a label and a "
            f"numeric value. Got {len(columns)}: {columns}."
        )
    labeled = [(r[0], r[1]) for r in rows if r[1] is not None]
    if len(labeled) < 2:
        raise ValueError("Need at least 2 non-null values to compute outliers.")
    labels = [label for label, _ in labeled]
    values = np.array([value for _, value in labeled], dtype=float)

    mean, std = float(values.mean()), float(values.std(ddof=1))
    if std == 0:
        return {
            "mode": "outliers",
            "n": len(values),
            "mean": mean,
            "stddev": 0.0,
            "z_threshold": z_threshold,
            "outliers": [],
            "note": "All values are identical; no outliers.",
        }

    z_scores = (values - mean) / std
    outliers = [
        {"label": labels[i], "value": float(values[i]), "z_score": float(z_scores[i])}
        for i in range(len(values))
        if abs(z_scores[i]) > z_threshold
    ]
    outliers.sort(key=lambda o: -abs(o["z_score"]))

    return {
        "mode": "outliers",
        "n": len(values),
        "mean": mean,
        "stddev": std,
        "z_threshold": z_threshold,
        "outliers": outliers,
    }


@tool
def run_stats(
    query: str,
    mode: Literal["describe", "compare_two_groups", "outliers"],
    z_threshold: float = 2.5,
) -> dict:
    """Run real statistical analysis (not just a SQL aggregate) on the result of a
    read-only query. Pick the mode based on what the question is actually asking:

    - "compare_two_groups": comparing two groups and the question is (implicitly or
      explicitly) about whether the difference is real, not just which average is
      numerically bigger. Runs a Welch's t-test and reports a p-value. The query MUST
      return exactly two columns: a group label and a numeric value, one row per
      observation. Example:
      SELECT CASE WHEN genre LIKE '%Action%' THEN 'action' ELSE 'other' END AS group_label,
             price_usd AS value FROM games
      Prefer this over computing two averages yourself with SQL when significance matters.

    - "outliers": finding anomalous/standout rows via z-score. The query MUST return
      exactly two columns: a label (e.g. name) and a numeric value.

    - "describe": summary statistics (mean, median, stddev, quartiles) for one numeric
      column. The query MUST return exactly one column.
    """
    return execute_run_stats(query, mode, z_threshold)
