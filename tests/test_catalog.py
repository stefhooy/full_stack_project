"""Tests for src/db/catalog.py (backs the frontend's /catalog browse page)
against the real, throwaway DuckDB file (the `games_db` fixture) — same
"real fixture, not a mock" approach as test_genre_stats.py.

Fixture rows (see conftest.py): Alpha Quest (Action/Adventure, metacritic
85, released 2022-06-01), Beta Raiders (Action/Indie, no metacritic score,
released 2019-03-15), Castle Strategy (Strategy, metacritic 90, no release
date), Free Arena (Action/Free To Play/Massively Multiplayer, no
metacritic score, no release date).
"""

from __future__ import annotations

import pytest

from src.config import settings
from src.db.catalog import list_games


@pytest.fixture(autouse=True)
def _point_settings_at_test_db(games_db, monkeypatch):
    monkeypatch.setattr(settings, "duckdb_path", games_db)


def test_list_games_returns_everything_by_default():
    games, total = list_games()
    assert total == 4
    assert len(games) == 4


def test_search_matches_on_a_name_substring_case_insensitively():
    games, total = list_games(q="raiders")
    assert total == 1
    assert games[0]["name"] == "Beta Raiders"


def test_search_with_no_match_returns_empty():
    games, total = list_games(q="nonexistent")
    assert games == []
    assert total == 0


def test_genre_filter_matches_on_token_not_substring():
    games, total = list_games(genre="Action")
    names = {g["name"] for g in games}
    assert names == {"Alpha Quest", "Beta Raiders", "Free Arena"}
    assert total == 3


def test_sort_by_metacritic_score_puts_nulls_last_on_descending():
    games, _ = list_games(sort="metacritic_score", order="desc")
    scores = [g["metacritic_score"] for g in games]
    # Castle Strategy (90), Alpha Quest (85), then the two NULLs -- nulls
    # never sort as if they were a real 0 or worse-than-real-score.
    assert scores[0] == 90
    assert scores[1] == 85
    assert scores[2] is None
    assert scores[3] is None


def test_sort_by_release_date_ascending_puts_nulls_last():
    games, _ = list_games(sort="release_date", order="asc")
    names = [g["name"] for g in games]
    # Beta Raiders (2019) before Alpha Quest (2022); the two undated games
    # come last regardless of ascending order, not first.
    assert names[0] == "Beta Raiders"
    assert names[1] == "Alpha Quest"
    assert set(names[2:]) == {"Castle Strategy", "Free Arena"}


def test_unknown_sort_key_falls_back_to_the_default_instead_of_raising():
    _games, total = list_games(sort="not_a_real_column")
    assert total == 4  # no exception, no data loss


def test_pagination_respects_page_size_and_page_number():
    page_one, total = list_games(sort="name", order="asc", page=1, page_size=2)
    page_two, _ = list_games(sort="name", order="asc", page=2, page_size=2)
    assert total == 4
    assert len(page_one) == 2
    assert len(page_two) == 2
    assert {g["name"] for g in page_one} != {g["name"] for g in page_two}


def test_page_size_is_capped_at_the_max():
    from src.db.catalog import MAX_PAGE_SIZE

    games, _ = list_games(page_size=MAX_PAGE_SIZE + 500)
    assert len(games) <= MAX_PAGE_SIZE


def test_page_beyond_the_last_one_returns_an_empty_list_not_an_error():
    games, total = list_games(page=99, page_size=10)
    assert games == []
    assert total == 4
