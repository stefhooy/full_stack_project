"""MCP server exposing this project's guarded database tools to any
MCP-compatible AI app (Claude Desktop, Claude Code, Cursor, ...) — not
just this project's own LangGraph agent.

Reuses the exact same implementations the agent uses
(execute_run_sql / execute_run_stats from src/tools/), so the safety
guarantees are identical: SELECT-only, table-allowlisted, row-capped,
enforced by the same code either way (src/db/connection.py). This server
is a thin protocol adapter, not a second implementation to keep in sync.

Local stdio transport only, deliberately (see DOCEXP.md's Slice 8 entry
for the full reasoning): whatever MCP client launches this process
supplies its own model, so this server needs no LLM API key and costs
nothing to run — no hosting, no network exposure, it only exists for the
duration of the calling app's session.

Run directly for a smoke test with the official MCP Inspector:
    uv run mcp dev src/mcp_server/server.py
Or point a real MCP client at it — see README.md's "MCP server" section
for exact Claude Desktop / Claude Code config.
"""

from __future__ import annotations

import duckdb
from mcp.server import MCPServer

from src.agent.rag.schema_corpus import SCHEMA_CHUNKS
from src.agent.rag.schema_index import assemble_schema_text
from src.db.connection import UnsafeQueryError
from src.tools.sql_tool import execute_run_sql
from src.tools.stats_tool import execute_run_stats

mcp = MCPServer(
    "ai-game-analyst",
    instructions=(
        "Query a real video game market dataset (SteamSpy catalog + a live "
        "player-count time series). Read the games-schema resource first so "
        "you know what columns exist. Every query is read-only and guarded: "
        "SELECT-only, allowlisted tables, capped rows — enforced in code, "
        "not by trusting whatever query you write."
    ),
)


@mcp.resource("schema://games")
def games_schema() -> str:
    """The full database schema: tables, columns, and the metric notes
    (unit conversions, join hints, known data-quality caveats) the agent's
    own system prompt uses — same source of truth, so this MCP server and
    the web app never describe the schema differently."""
    return assemble_schema_text(SCHEMA_CHUNKS)


@mcp.tool()
def run_sql(query: str) -> dict:
    """Run a single read-only SQL SELECT statement (DuckDB dialect, CTEs
    OK) against the games catalog and/or player_counts time series, and
    return the resulting rows as JSON. Rows are capped server-side. Read
    the schema://games resource first if you haven't already — it has the
    exact column names, types, and gotchas (e.g. how to compute a single
    'owners' number, which columns need a JOIN)."""
    try:
        return execute_run_sql(query)
    except (UnsafeQueryError, duckdb.Error) as e:
        return {"error": str(e)}


@mcp.tool()
def run_stats(query: str, mode: str, z_threshold: float = 2.5) -> dict:
    """Run real statistical analysis (not just a SQL aggregate) on the
    result of a read-only query. mode="compare_two_groups": a Welch's
    t-test between two groups, reports a p-value — query must return
    exactly two columns, a group label and a numeric value, one row per
    observation. mode="outliers": z-score anomaly detection — query must
    return exactly two columns, a label and a numeric value. mode="describe":
    summary statistics for one numeric column — query must return exactly
    one column."""
    try:
        return execute_run_stats(query, mode, z_threshold)
    except (UnsafeQueryError, duckdb.Error, ValueError) as e:
        return {"error": str(e)}


if __name__ == "__main__":
    mcp.run()
