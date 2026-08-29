"""Shared pytest fixtures.

The guiding rule for this whole test suite: prefer a real, throwaway
DuckDB file over mocking this project's own DB layer. A guarded
connection, a real CREATE TABLE, and real rows catch things a mock of
"what we assume the DB does" never could — the same reasoning the project
already applies everywhere else (verify against the real thing, not an
assumption of it).
"""

from __future__ import annotations

from datetime import date, datetime

import duckdb
import pytest

from src.db.schema import CREATE_GAMES_TABLE_SQL, CREATE_PLAYER_COUNTS_TABLE_SQL


@pytest.fixture()
def games_db(tmp_path):
    """A real DuckDB file, schema created for real, seeded with a small,
    hand-picked set of rows spanning several genres — enough to exercise
    genre counting/filtering without needing the real ~1000-game catalog."""
    db_path = tmp_path / "test_games.duckdb"
    conn = duckdb.connect(str(db_path))
    conn.execute(CREATE_GAMES_TABLE_SQL)
    conn.execute(CREATE_PLAYER_COUNTS_TABLE_SQL)

    rows = [
        # appid, name, developer, publisher, genre, languages, positive, negative,
        # review_score, owners_low, owners_high, playtime_forever, playtime_2weeks,
        # price, initial_price, discount, peak_ccu, release_date, release_date_raw,
        # metacritic_score, platforms, categories, ingested_at
        (1, "Alpha Quest", "Dev A", "Pub A", "Action, Adventure", "English",
         900, 100, 0.9, 100_000, 200_000, 0, 0, 19.99, 19.99, 0.0, 500,
         date(2022, 6, 1), "1 Jun, 2022", 85, "windows,mac",
         "Single-player,Steam Achievements", datetime.now()),
        (2, "Beta Raiders", "Dev B", "Pub B", "Action, Indie", "English",
         400, 400, 0.5, 10_000, 20_000, 0, 0, 4.99, 9.99, 50.0, 20,
         date(2019, 3, 15), "15 Mar, 2019", None, "windows", "Single-player", datetime.now()),
        (3, "Castle Strategy", "Dev C", "Pub C", "Strategy", "English, French",
         700, 50, 700 / 750, 50_000, 100_000, 0, 0, 29.99, 29.99, 0.0, 80,
         None, None, 90, "windows,mac,linux", "Multi-player,Steam Workshop", datetime.now()),
        (4, "Free Arena", "Dev D", "Pub D", "Action, Free To Play, Massively Multiplayer",
         "English", 5000, 5000, 0.5, 1_000_000, 2_000_000, 0, 0, 0.0, 0.0, 0.0, 9000,
         None, None, None, "windows", "Multi-player,PvP", datetime.now()),
    ]
    conn.executemany(
        """INSERT INTO games (
            appid, name, developer, publisher, genre, languages,
            positive_reviews, negative_reviews, review_score,
            owners_low, owners_high,
            average_playtime_forever_min, average_playtime_2weeks_min,
            price_usd, initial_price_usd, discount_pct, peak_ccu,
            release_date, release_date_raw, metacritic_score, platforms, categories,
            ingested_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.close()
    return str(db_path)
