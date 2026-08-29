"""Tests for src/db/connection.py — the one safety boundary in the whole
system (see that module's own docstring). This has been exercised by hand
repeatedly throughout the project's history (a real DROP TABLE sent through
both the agent and the MCP server, confirmed rejected identically — see
DOCEXP.md's Slice 8 entry) but never had a checked-in regression suite
until now. These tests capture that manual verification as something that
runs on every change, not just something someone remembered to try once.
"""

from __future__ import annotations

import pytest

from src.db.connection import UnsafeQueryError, validate_select_only


def test_allows_a_plain_select():
    sql = validate_select_only("SELECT name FROM games", max_rows=200)
    assert "SELECT" in sql.upper()
    assert "games" in sql


def test_allows_a_cte():
    sql = validate_select_only(
        "WITH top AS (SELECT name FROM games) SELECT * FROM top", max_rows=200
    )
    assert "top" in sql.lower()


@pytest.mark.parametrize(
    "sql",
    [
        "DROP TABLE games",
        "DELETE FROM games",
        "UPDATE games SET price_usd = 0",
        "INSERT INTO games (appid) VALUES (1)",
        "ATTACH 'evil.db' AS evil",
        "CREATE TABLE evil (x INT)",
    ],
)
def test_rejects_anything_that_is_not_a_select(sql):
    with pytest.raises(UnsafeQueryError):
        validate_select_only(sql, max_rows=200)


def test_rejects_multiple_statements():
    with pytest.raises(UnsafeQueryError, match="one SQL statement"):
        validate_select_only("SELECT 1; DROP TABLE games", max_rows=200)


def test_rejects_a_disallowed_table():
    with pytest.raises(UnsafeQueryError, match="allowlist"):
        validate_select_only("SELECT * FROM sqlite_master", max_rows=200)


def test_rejects_union_across_two_selects():
    # Not a security hole (both sides are still plain SELECTs against
    # allowlisted tables) but explicitly unsupported — see
    # src/agent/prompts.py's "no_union" rule; conditional aggregation is
    # the sanctioned way to compare two groups in one query instead.
    with pytest.raises(UnsafeQueryError):
        validate_select_only(
            "SELECT name FROM games UNION SELECT name FROM games", max_rows=200
        )


def test_injects_a_limit_when_the_query_has_none():
    sql = validate_select_only("SELECT name FROM games", max_rows=50)
    assert "LIMIT 50" in sql.upper()


def test_caps_a_limit_that_exceeds_max_rows():
    sql = validate_select_only("SELECT name FROM games LIMIT 10000", max_rows=50)
    assert "LIMIT 50" in sql.upper()


def test_leaves_a_limit_under_the_cap_alone():
    sql = validate_select_only("SELECT name FROM games LIMIT 5", max_rows=50)
    assert "LIMIT 5" in sql.upper()
    assert "LIMIT 50" not in sql.upper()


def test_a_real_drop_table_is_rejected_end_to_end(games_db):
    """The exact scenario DOCEXP.md's Slice 8 entry verified by hand against
    a live MCP session — same guard, same guarantee, now a real regression
    test instead of a one-time manual check."""
    import duckdb

    from src.db.connection import run_guarded_query

    conn = duckdb.connect(games_db, read_only=True)
    try:
        with pytest.raises(UnsafeQueryError):
            run_guarded_query(conn, "DROP TABLE games", max_rows=200)
        # And the table really is still there and queryable afterward.
        _columns, rows = run_guarded_query(conn, "SELECT COUNT(*) FROM games", max_rows=200)
        assert rows[0][0] == 4
    finally:
        conn.close()
