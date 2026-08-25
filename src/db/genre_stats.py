"""Live genre-prevalence stats for the frontend's genre showcase.

Computed at request time from whatever's actually in `games` right now —
deliberately NOT a snapshot baked into frontend source. SteamSpy's `genre`
field is a comma-joined free-text list (see
src/ingestion/steamspy_client.py), so this splits and counts tokens exactly
the way the Slice 9 frontend design work first did by hand, one-off, against
a local export — the difference is this runs live against the DB every time
the frontend asks, so both the counts AND which genres make the top N stay
correct as `refresh_catalog.yml` re-ingests and the catalog grows or shifts,
instead of drifting stale the moment the catalog changes.
"""

from __future__ import annotations

import duckdb

from src.config import settings

# Real tags SteamSpy emits in the same comma-joined field that aren't
# genres: a release status and a pricing model. Excluded regardless of
# prevalence — see DOCEXP.md's Slice 9 entry for the original by-hand count
# that established this list.
_EXCLUDED_TAGS = {"Early Access", "Free To Play"}

# The dataviz skill's categorical palette is an 8-hue cap, not a
# suggestion — see palette.md. A 9th genre never gets a generated hue, so
# the frontend only ever draws the top 8.
TOP_N = 8


def get_genre_counts(top_n: int = TOP_N) -> list[dict]:
    conn = duckdb.connect(settings.duckdb_abs_path, read_only=True)
    try:
        rows = conn.execute("SELECT genre FROM games WHERE genre IS NOT NULL").fetchall()
    finally:
        conn.close()

    counts: dict[str, int] = {}
    for (genre_field,) in rows:
        for token in genre_field.split(","):
            label = token.strip()
            if not label or label in _EXCLUDED_TAGS:
                continue
            counts[label] = counts.get(label, 0) + 1

    # Sort by count desc, then label asc for a stable tie-break — without
    # this, ties would order however dict iteration happens to land, which
    # would make the frontend's hue assignment (position-ordered, see
    # GenreShowcase.tsx) nondeterministic across requests.
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top_n]
    return [{"label": label, "count": count} for label, count in ranked]


def get_games_by_genre(label: str, limit: int = 12) -> list[dict]:
    """The actual games behind a genre showcase card — what "click a genre,
    see the games" needs. Matches on the comma-split token, not a raw
    ILIKE substring, for the same reason get_genre_counts() splits rather
    than pattern-matches: a substring match on the whole free-text field
    risks a false positive (e.g. a hypothetical genre containing another
    genre's name as a substring) that a token-equality check can't have.
    """
    conn = duckdb.connect(settings.duckdb_abs_path, read_only=True)
    try:
        rows = conn.execute(
            "SELECT name, genre, price_usd, review_score, peak_ccu FROM games "
            "WHERE genre IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()

    target = label.strip().lower()
    matches = [
        {
            "name": name,
            "price_usd": price_usd,
            "review_score": review_score,
            "peak_ccu": peak_ccu,
        }
        for name, genre_field, price_usd, review_score, peak_ccu in rows
        if target in {t.strip().lower() for t in genre_field.split(",")}
    ]
    matches.sort(
        key=lambda g: (
            g["review_score"] if g["review_score"] is not None else -1,
            g["peak_ccu"] if g["peak_ccu"] is not None else -1,
        ),
        reverse=True,
    )
    return matches[:limit]
