"""Backs the frontend's full catalog page (/catalog) — search, genre
filter, sort, and pagination over the whole ~1000-game catalog.

Filters and sorts in Python rather than building dynamic SQL: the sort
column comes from user input, and interpolating a column name into SQL
(can't be a bound parameter) means either an allowlist or a real
injection risk — the allowlist here is just a Python dict instead.
Genre filtering reuses genre_stats.py's same comma-split token-match
approach (SteamSpy's `genre` field is free-text, comma-joined) for the
same reason get_games_by_genre() does it that way: a raw ILIKE substring
match on the whole field risks a false positive against another genre's
name. At ~1000 rows, pulling the whole table into Python for this is
comfortably fast and avoids a second genre-matching implementation
drifting from the first.
"""

from __future__ import annotations

from typing import Any, Callable

import duckdb

from src.config import settings

_CATALOG_COLUMNS = [
    "name",
    "developer",
    "publisher",
    "genre",
    "release_date",
    "metacritic_score",
    "platforms",
    "categories",
    "price_usd",
    "review_score",
    "owners_low",
    "owners_high",
    "peak_ccu",
]

# Each key is a sort option the frontend can request, mapped to the row
# field it reads. A game with no Metacritic score isn't "worst," it's just
# unscored (see schema_corpus.py's same warning) — same for a missing
# release date or price -- so NULLs are always sorted to the end,
# regardless of ascending/descending. That can't be done with a single
# floor value + `reverse=`: flooring NULLs to a low sentinel puts them
# last on descending but *first* on ascending (found by actually running
# this sort both directions, not assumed) -- list_games() below instead
# sorts the non-NULL rows and appends the NULL ones after, unaffected by
# `reverse`.
_SORT_FIELDS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "name": lambda g: g["name"],
    "release_date": lambda g: g["release_date"],
    "metacritic_score": lambda g: g["metacritic_score"],
    "price_usd": lambda g: g["price_usd"],
    "review_score": lambda g: g["review_score"],
    "peak_ccu": lambda g: g["peak_ccu"],
    "owners_high": lambda g: g["owners_high"],
}
DEFAULT_SORT = "peak_ccu"
DEFAULT_PAGE_SIZE = 24
MAX_PAGE_SIZE = 100


def list_games(
    *,
    q: str | None = None,
    genre: str | None = None,
    sort: str = DEFAULT_SORT,
    order: str = "desc",
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> tuple[list[dict[str, Any]], int]:
    """Returns (page of games, total matching count before pagination)."""
    conn = duckdb.connect(settings.duckdb_abs_path, read_only=True)
    try:
        rows = conn.execute(f"SELECT {', '.join(_CATALOG_COLUMNS)} FROM games").fetchall()
    finally:
        conn.close()

    games = [dict(zip(_CATALOG_COLUMNS, row)) for row in rows]

    if q and q.strip():
        needle = q.strip().lower()
        games = [g for g in games if needle in (g["name"] or "").lower()]

    if genre and genre.strip():
        target = genre.strip().lower()
        games = [
            g
            for g in games
            if g["genre"] and target in {t.strip().lower() for t in g["genre"].split(",")}
        ]

    value_fn = _SORT_FIELDS.get(sort, _SORT_FIELDS[DEFAULT_SORT])
    with_value = [g for g in games if value_fn(g) is not None]
    without_value = [g for g in games if value_fn(g) is None]
    sort_key = (lambda g: value_fn(g).lower()) if sort == "name" else value_fn
    with_value.sort(key=sort_key, reverse=(order != "asc"))
    games = with_value + without_value

    total = len(games)
    page = max(page, 1)
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    start = (page - 1) * page_size
    return games[start : start + page_size], total
