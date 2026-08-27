"""Tests for src/db/genre_stats.py against a real, throwaway DuckDB file
(the `games_db` fixture in conftest.py) — not a mock of the DB layer.
`get_genre_counts`/`get_games_by_genre` read `settings.duckdb_abs_path`
internally rather than taking a path argument, so these tests monkeypatch
`settings.duckdb_path` to point at the fixture DB for the duration of the
test, then call the real functions unmodified.
"""

from __future__ import annotations

import pytest

from src.config import settings
from src.db.genre_stats import get_games_by_genre, get_genre_counts


@pytest.fixture(autouse=True)
def _point_settings_at_test_db(games_db, monkeypatch):
    monkeypatch.setattr(settings, "duckdb_path", games_db)


def test_genre_counts_splits_comma_joined_genres_and_counts_tokens():
    # Fixture rows: Alpha Quest (Action, Adventure), Beta Raiders (Action,
    # Indie), Castle Strategy (Strategy), Free Arena (Action, Free To Play,
    # Massively Multiplayer) -- Action appears in 3 rows.
    counts = {row["label"]: row["count"] for row in get_genre_counts()}
    assert counts["Action"] == 3
    assert counts["Adventure"] == 1
    assert counts["Strategy"] == 1
    assert counts["Massively Multiplayer"] == 1


def test_genre_counts_excludes_non_genre_tags():
    counts = {row["label"] for row in get_genre_counts()}
    assert "Free To Play" not in counts
    assert "Early Access" not in counts


def test_genre_counts_respects_top_n():
    assert len(get_genre_counts(top_n=2)) == 2


def test_genre_counts_orders_by_count_descending():
    counts = get_genre_counts()
    values = [row["count"] for row in counts]
    assert values == sorted(values, reverse=True)


def test_games_by_genre_matches_on_token_not_substring():
    # "Action" should not accidentally match a hypothetical genre that
    # merely contains "Action" as a substring -- token-equality matching
    # (not raw ILIKE '%Action%') is the whole point, see genre_stats.py.
    games = get_games_by_genre("Action")
    names = {g["name"] for g in games}
    assert names == {"Alpha Quest", "Beta Raiders", "Free Arena"}


def test_games_by_genre_sorts_by_review_score_then_peak_ccu():
    games = get_games_by_genre("Action")
    # Alpha Quest (0.9) should outrank Beta Raiders (0.5) and Free Arena (0.5).
    assert games[0]["name"] == "Alpha Quest"


def test_games_by_genre_respects_limit():
    games = get_games_by_genre("Action", limit=1)
    assert len(games) == 1


def test_games_by_genre_returns_empty_list_for_an_unknown_genre():
    assert get_games_by_genre("Nonexistent Genre") == []
