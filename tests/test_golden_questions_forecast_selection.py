"""Tests for build_golden_questions()'s dynamic forecast-question
selection (DOCEXP.md's Slice 54 entry): the two "has a real projection"
golden questions used to hardcode "Counter-Strike: Global Offensive" and
"Hearts of Iron IV" -- a real, confirmed bug, since CI's small, freshly-
built catalog doesn't guarantee either name survives. Now picked live
from whichever tracked games actually qualify, 0/1/2 of them, never
assumed to be exactly 2 -- these tests pin down that range directly,
using the real games_db fixture (a real DuckDB file, not a mock).
"""

from __future__ import annotations

import duckdb
import pytest

from src.config import settings
from src.evals.golden_questions import build_golden_questions


def _insert_player_counts(db_path: str, appid: int, n_snapshots: int) -> None:
    conn = duckdb.connect(db_path)
    conn.executemany(
        "INSERT INTO player_counts (appid, player_count, polled_at) VALUES (?, ?, ?)",
        [(appid, 100 + i, f"2026-01-{i + 1:02d} 00:00:00") for i in range(n_snapshots)],
    )
    conn.close()


@pytest.fixture(autouse=True)
def _use_games_db(games_db, monkeypatch):
    monkeypatch.setattr(settings, "duckdb_path", games_db)
    return games_db


def _forecast_real_projection_questions(games_db):
    return [q for q in build_golden_questions() if q.id.startswith("forecast_tracked_game_")]


def test_zero_tracked_games_produces_zero_forecast_questions(games_db):
    # games_db seeds `games` but leaves `player_counts` empty -- exactly
    # the "nothing qualifies yet" case.
    assert _forecast_real_projection_questions(games_db) == []
    # The rest of the golden set must still build cleanly -- an empty
    # forecast slot must never crash the whole function.
    assert len(build_golden_questions()) > 0


def test_one_tracked_game_produces_exactly_one_forecast_question(games_db):
    _insert_player_counts(games_db, appid=4, n_snapshots=3)  # "Free Arena", peak_ccu=9000
    questions = _forecast_real_projection_questions(games_db)
    assert len(questions) == 1
    assert questions[0].id == "forecast_tracked_game_1_next_month"
    assert "Free Arena" in questions[0].question
    assert "next month" in questions[0].question


def test_two_tracked_games_produces_two_distinct_forecast_questions(games_db):
    _insert_player_counts(games_db, appid=4, n_snapshots=3)  # "Free Arena", peak_ccu=9000
    _insert_player_counts(games_db, appid=1, n_snapshots=2)  # "Alpha Quest", peak_ccu=500
    questions = _forecast_real_projection_questions(games_db)
    assert len(questions) == 2
    assert questions[0].id == "forecast_tracked_game_1_next_month"
    assert questions[1].id == "forecast_tracked_game_2_next_week"
    # Ordered by peak_ccu DESC: Free Arena (9000) before Alpha Quest (500).
    assert "Free Arena" in questions[0].question
    assert "Alpha Quest" in questions[1].question
    assert "next month" in questions[0].question
    assert "next week" in questions[1].question


def test_a_game_with_only_one_snapshot_does_not_qualify(games_db):
    # _forecast() itself needs >= 2 distinct snapshots to fit any trend --
    # a game with just one shouldn't be picked as "has enough history."
    _insert_player_counts(games_db, appid=4, n_snapshots=1)
    assert _forecast_real_projection_questions(games_db) == []


def test_reference_facts_report_the_real_snapshot_count(games_db):
    _insert_player_counts(games_db, appid=4, n_snapshots=5)
    questions = _forecast_real_projection_questions(games_db)
    assert "5 real historical live-player snapshots" in questions[0].reference_facts
