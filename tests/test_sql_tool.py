"""Tests for src/tools/sql_tool.py against a real, throwaway DuckDB file
(the `games_db` fixture in conftest.py), not a mock of the DB layer.

execute_run_sql's own docstring promises "a JSON-serializable result" --
this file exists because that promise was real but unenforced: a real,
reproduced production bug (a genuine "how has WEBFISHING's player count
changed over time?" follow-up question, Slice 63/64's own generated
suggestion) crashed with `TypeError: Object of type datetime is not JSON
serializable` inside execute_tools_node's json.dumps(), the first time a
real question selected a DATE/TIMESTAMP column for display.
"""

from __future__ import annotations

import json

import pytest

from src.config import settings
from src.tools.sql_tool import execute_run_sql


@pytest.fixture(autouse=True)
def _point_settings_at_test_db(games_db, monkeypatch):
    monkeypatch.setattr(settings, "duckdb_path", games_db)


def test_a_date_column_comes_back_as_an_iso_string_not_a_date_object():
    result = execute_run_sql("SELECT name, release_date FROM games WHERE appid = 1")
    assert result["rows"] == [["Alpha Quest", "2022-06-01"]]


def test_a_timestamp_column_comes_back_as_an_iso_string_not_a_datetime_object():
    result = execute_run_sql("SELECT appid, ingested_at FROM games WHERE appid = 1")
    row = result["rows"][0]
    assert isinstance(row[1], str)
    # A real isoformat() string, not str()'s slightly different rendering
    # (space instead of "T") -- matches forecast_tool.py's own convention.
    assert "T" in row[1]


def test_a_null_date_column_stays_null():
    # Castle Strategy's fixture row has release_date=None -- confirms the
    # isinstance check doesn't choke on (or accidentally stringify) a
    # real NULL.
    result = execute_run_sql("SELECT name, release_date FROM games WHERE appid = 3")
    assert result["rows"] == [["Castle Strategy", None]]


def test_the_full_result_is_actually_json_dumpable():
    # The real, exact failure mode this bug caused: execute_tools_node
    # calls json.dumps() directly on this dict to build a ToolMessage.
    # Asserting on the shape isn't enough -- this is the one guarantee
    # execute_run_sql's own docstring already claims to make.
    result = execute_run_sql(
        "SELECT name, release_date, ingested_at FROM games ORDER BY appid"
    )
    json.dumps(result)  # must not raise


def test_a_non_date_result_is_unaffected():
    result = execute_run_sql("SELECT name, price_usd FROM games WHERE appid = 1")
    assert result["rows"] == [["Alpha Quest", 19.99]]
