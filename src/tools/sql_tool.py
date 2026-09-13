"""The agent's one tool: run_sql.

`execute_run_sql` is the real implementation, called directly (not via
LangChain's tool-invocation machinery) by the graph's execute_tools node in
src/agent/graph.py, that keeps the self-correction/error-handling logic
visible in the graph rather than hidden inside the tool wrapper.

`run_sql` (the @tool-decorated wrapper) exists only to hand the LLM a
schema via .bind_tools([run_sql]); the graph never calls run_sql.invoke().
"""

from __future__ import annotations

import datetime

from langchain_core.tools import tool

from src.config import settings
from src.db.connection import get_read_only_connection, run_guarded_query


def _json_safe(value: object) -> object:
    """DuckDB hands back real Python date/datetime objects for DATE/
    TIMESTAMP columns (games.release_date, games.ingested_at,
    player_counts.polled_at) -- not JSON-serializable on their own, even
    though this function's own docstring already promised a JSON-
    serializable result. Found via a real, reproduced production bug: a
    genuine "how has X's player count changed over time" question (one
    of Slice 63/64's own follow-up suggestions, for a real game,
    WEBFISHING) crashed with `TypeError: Object of type datetime is not
    JSON serializable` inside execute_tools_node's json.dumps(), not a
    hypothetical edge case. `datetime.datetime` is itself a subclass of
    `datetime.date`, so one isinstance check covers both DATE and
    TIMESTAMP columns. Converts to the same isoformat() string this
    project already uses for datetimes elsewhere (forecast_tool.py's own
    output), not a generic str()."""
    if isinstance(value, datetime.date):
        return value.isoformat()
    return value


def execute_run_sql(query: str) -> dict:
    """Run a guarded, read-only query and return a JSON-serializable result."""
    conn = get_read_only_connection(settings.duckdb_abs_path)
    try:
        columns, rows = run_guarded_query(conn, query, settings.sql_max_rows)
    finally:
        conn.close()
    return {
        "columns": columns,
        "rows": [[_json_safe(v) for v in r] for r in rows],
        "row_count": len(rows),
    }


@tool
def run_sql(query: str) -> dict:
    """Run a single read-only SQL SELECT statement against the `games` table
    and return the resulting rows as JSON. The query must be valid DuckDB SQL,
    a single SELECT statement (CTEs are fine), and only reference the `games`
    table. Rows are automatically capped server-side."""
    return execute_run_sql(query)
