"""Unit tests for the MCP server's exposed tools (src/mcp_server/server.py).
The @mcp.tool()/@mcp.resource() decorators register but don't replace the
underlying function (confirmed directly: run_sql etc. are still plain,
directly-callable functions after decoration), so these call them the same
way an MCP client would, against a real, throwaway DuckDB fixture -- same
"real DB over mocking this project's own layer" approach as the rest of
this suite.
"""

from __future__ import annotations

import pytest

from src.config import settings
from src.mcp_server.server import games_schema, run_sql, run_stats


@pytest.fixture(autouse=True)
def _point_settings_at_test_db(games_db, monkeypatch):
    monkeypatch.setattr(settings, "duckdb_path", games_db)


def test_run_sql_returns_real_rows_for_a_valid_query():
    result = run_sql("SELECT name FROM games ORDER BY peak_ccu DESC LIMIT 1")
    assert "error" not in result
    assert result["rows"][0][0] == "Free Arena"  # the games_db fixture's highest-peak_ccu row


def test_run_sql_returns_an_error_dict_not_a_raised_exception_for_unsafe_queries():
    # This is the actual contract MCP clients depend on: a bad/unsafe query
    # is a normal-looking dict response with an "error" key, never an
    # exception that would crash the calling client's tool-call handling.
    result = run_sql("DROP TABLE games")
    assert "error" in result
    assert isinstance(result["error"], str)


def test_run_sql_returns_an_error_dict_for_genuinely_invalid_sql():
    result = run_sql("SELECT this is not valid sql at all")
    assert "error" in result


def test_run_stats_returns_real_results_for_a_valid_query():
    result = run_stats(
        "SELECT price_usd FROM games WHERE genre LIKE '%Action%'",
        mode="describe",
    )
    assert "error" not in result
    assert result["mode"] == "describe"


def test_run_stats_returns_an_error_dict_for_an_unsafe_query():
    result = run_stats("DROP TABLE games", mode="describe")
    assert "error" in result


def test_run_stats_returns_an_error_dict_for_an_invalid_mode():
    result = run_stats("SELECT price_usd FROM games", mode="not_a_real_mode")
    assert "error" in result


def test_games_schema_resource_returns_real_schema_text_not_empty():
    text = games_schema()
    assert isinstance(text, str)
    assert "games" in text.lower()
    assert len(text) > 100
