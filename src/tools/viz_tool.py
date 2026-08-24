"""Chart-spec inference: turns a query result (columns + rows) into a small,
frontend-agnostic chart spec.

Deliberately NOT an LLM tool. Chart type only needs to be inferred from the
*shape* of the result (how many columns, what Python type each holds) —
that's a deterministic decision code can make correctly every time, so
there's no ambiguity to spend an LLM call resolving. Consistent with the
project's general approach of using code, not a prompt, wherever a question
has one clearly correct mechanical answer (see the SQL safety guard for the
same reasoning applied to something higher-stakes).

The spec is intentionally minimal and framework-agnostic (not tied to
Vega-Lite, Chart.js, Recharts, etc.) — a {type, x, y, data} shape any
frontend charting library can consume. Whichever one Slice 6's frontend
ends up using, this doesn't need to change.
"""

from __future__ import annotations

NUMERIC_TYPES = (int, float)


def infer_chart_spec(columns: list[str] | None, rows: list[list] | None) -> dict | None:
    if not columns or not rows or len(rows) < 2:
        # A single row (or no rows) is a fact, not a distribution — nothing
        # meaningful to chart. Let the frontend show the number/table as-is.
        return None

    if len(columns) != 2:
        # 1 column: no obvious x-axis. 3+: which two matter is ambiguous
        # without asking the LLM, which defeats the point of doing this
        # deterministically — punt to a plain table rather than guess.
        return None

    sample_row = rows[0]
    first_is_numeric = isinstance(sample_row[0], NUMERIC_TYPES)
    second_is_numeric = isinstance(sample_row[1], NUMERIC_TYPES)

    if first_is_numeric and second_is_numeric:
        chart_type = "scatter"
    elif not first_is_numeric and second_is_numeric:
        chart_type = "bar"
    elif first_is_numeric and not second_is_numeric:
        # Numeric first, label second — swap so the label reads as the
        # category axis, matching how "top N games by X" queries are
        # naturally written (name first) vs. answered (value could be first).
        columns = [columns[1], columns[0]]
        rows = [[r[1], r[0]] for r in rows]
        chart_type = "bar"
    else:
        return None  # two non-numeric columns: nothing to plot

    return {
        "type": chart_type,
        "x": {"field": columns[0]},
        "y": {"field": columns[1]},
        "data": [{columns[0]: r[0], columns[1]: r[1]} for r in rows],
    }
