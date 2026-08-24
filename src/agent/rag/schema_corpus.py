"""The RAG corpus: small, independently-retrievable facts about the DB
schema, instead of one big hardcoded description string.

This is Slice 1's `GAMES_TABLE_DESCRIPTION` broken into chunks — same facts,
same wording, just split so retrieval can pick only the ones a given
question needs. Three kinds of chunk:

  - "table":       one per table, a one-line orientation ("what is this table").
  - "column":      one per column (name, type, meaning).
  - "metric_note": a handful of gotchas that aren't tied to one column (e.g.
                    "owners is a range, use the midpoint") — these matter a
                    lot for getting the SQL right and are easy to miss if
                    buried in a wall of column definitions.

Adding a table (Slice 7's player_counts) or a new metric note later means
appending chunks here, not rewriting a paragraph.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.db.schema import GAMES_TABLE


@dataclass(frozen=True)
class SchemaChunk:
    id: str
    kind: Literal["table", "column", "metric_note"]
    text: str
    always_include: bool = False
    """Bypass ranking and always retrieve this chunk. Reserved for context
    that's structurally relevant to nearly every question regardless of
    semantic similarity to the query text — see the `name` column below for
    why this exists (semantic search alone misses it)."""


GAMES_SCHEMA_CHUNKS: list[SchemaChunk] = [
    SchemaChunk(
        id="table:games",
        kind="table",
        text=f"Table: {GAMES_TABLE}. One row per Steam game (source: SteamSpy).",
        always_include=True,
    ),
    SchemaChunk(
        id="column:appid",
        kind="column",
        text=f"Column {GAMES_TABLE}.appid: BIGINT. Steam app id, primary key.",
    ),
    SchemaChunk(
        id="column:name",
        kind="column",
        text=f"Column {GAMES_TABLE}.name: VARCHAR. Game title.",
        # Semantic search alone misses this: a question naming a specific game
        # (e.g. "How many owners does Palworld have?") doesn't embed close to
        # a generic description like "Game title" — but nearly every question
        # needs this column to identify or filter which game(s) it's about.
        # Found empirically while testing retrieval quality; see DOCEXP.md.
        always_include=True,
    ),
    SchemaChunk(
        id="column:developer",
        kind="column",
        text=f"Column {GAMES_TABLE}.developer: VARCHAR. Developer name(s), comma-separated.",
    ),
    SchemaChunk(
        id="column:publisher",
        kind="column",
        text=f"Column {GAMES_TABLE}.publisher: VARCHAR. Publisher name(s), comma-separated.",
    ),
    SchemaChunk(
        id="column:genre",
        kind="column",
        text=(
            f"Column {GAMES_TABLE}.genre: VARCHAR. Comma-separated genres, "
            "e.g. 'Action, Indie'. Match with LIKE '%Genre%', not '='."
        ),
        # Same reasoning as column:name: a question naming a specific genre
        # ("RPG games", "Action tagged") doesn't embed close to the generic
        # description "comma-separated genres" — confirmed missing from
        # top-10 retrieval on two independent genre-filtering test questions.
        # Genre is one of the most commonly filtered dimensions here, so
        # this one's worth forcing in rather than accepting the gap.
        always_include=True,
    ),
    SchemaChunk(
        id="column:languages",
        kind="column",
        text=f"Column {GAMES_TABLE}.languages: VARCHAR. Comma-separated supported languages.",
    ),
    SchemaChunk(
        id="column:positive_reviews",
        kind="column",
        text=f"Column {GAMES_TABLE}.positive_reviews: INTEGER. Count of positive Steam reviews.",
    ),
    SchemaChunk(
        id="column:negative_reviews",
        kind="column",
        text=f"Column {GAMES_TABLE}.negative_reviews: INTEGER. Count of negative Steam reviews.",
    ),
    SchemaChunk(
        id="column:review_score",
        kind="column",
        text=(
            f"Column {GAMES_TABLE}.review_score: DOUBLE. "
            "positive_reviews / (positive_reviews + negative_reviews), range 0..1, "
            "NULL if the game has no reviews. This is the column to use for "
            "'highest rated' or 'best reviewed' questions."
        ),
    ),
    SchemaChunk(
        id="column:owners_low",
        kind="column",
        text=f"Column {GAMES_TABLE}.owners_low: BIGINT. Lower bound of estimated owners.",
    ),
    SchemaChunk(
        id="column:owners_high",
        kind="column",
        text=f"Column {GAMES_TABLE}.owners_high: BIGINT. Upper bound of estimated owners.",
    ),
    SchemaChunk(
        id="column:average_playtime_forever_min",
        kind="column",
        text=(
            f"Column {GAMES_TABLE}.average_playtime_forever_min: INTEGER. "
            "All-time average playtime, in minutes."
        ),
    ),
    SchemaChunk(
        id="column:average_playtime_2weeks_min",
        kind="column",
        text=(
            f"Column {GAMES_TABLE}.average_playtime_2weeks_min: INTEGER. "
            "Average playtime in the last 2 weeks, in minutes."
        ),
    ),
    SchemaChunk(
        id="column:price_usd",
        kind="column",
        text=(
            f"Column {GAMES_TABLE}.price_usd: DOUBLE. Current price in USD. "
            "0 means free-to-play."
        ),
    ),
    SchemaChunk(
        id="column:initial_price_usd",
        kind="column",
        text=f"Column {GAMES_TABLE}.initial_price_usd: DOUBLE. Pre-discount price in USD.",
    ),
    SchemaChunk(
        id="column:discount_pct",
        kind="column",
        text=f"Column {GAMES_TABLE}.discount_pct: DOUBLE. Current discount percentage, 0-100.",
    ),
    SchemaChunk(
        id="column:peak_ccu",
        kind="column",
        text=(
            f"Column {GAMES_TABLE}.peak_ccu: INTEGER. Peak concurrent players yesterday. "
            "Use this for 'most players right now' / 'concurrent players' questions."
        ),
    ),
    SchemaChunk(
        id="column:ingested_at",
        kind="column",
        text=f"Column {GAMES_TABLE}.ingested_at: TIMESTAMP. When this row was last refreshed.",
    ),
    SchemaChunk(
        id="metric:owners_midpoint",
        kind="metric_note",
        text=(
            "Owners are a SteamSpy *estimate range* (owners_low, owners_high), not an "
            "exact count. When a question needs a single 'number of owners' figure, use "
            "(owners_low + owners_high) / 2 as the midpoint estimate."
        ),
    ),
    SchemaChunk(
        id="metric:playtime_units",
        kind="metric_note",
        text=(
            "Playtime columns (average_playtime_forever_min, average_playtime_2weeks_min) "
            "are in minutes. Divide by 60 to answer a question asked in hours."
        ),
    ),
    SchemaChunk(
        id="metric:playtime_often_zero",
        kind="metric_note",
        text=(
            "Known data quality issue: average_playtime_forever_min and "
            "average_playtime_2weeks_min are 0 for most or all games in this dataset — "
            "SteamSpy has been unable to reliably compute playtime since a 2018 Steam "
            "privacy API change; this is not missing or broken ingestion. If a playtime "
            "query returns 0 (or the same value) across many/all games, say so explicitly "
            "in your answer as a data limitation rather than presenting it as a real finding."
        ),
    ),
    SchemaChunk(
        id="metric:review_score_is_fraction",
        kind="metric_note",
        text=(
            "review_score is a fraction between 0 and 1, not a percentage. "
            "Multiply by 100 if the question asks for a percentage."
        ),
    ),
    SchemaChunk(
        id="metric:no_union",
        kind="metric_note",
        text=(
            "To compare two groups (e.g. Action games vs. free-to-play games) in one "
            "query, use conditional aggregation — AVG(CASE WHEN <condition> THEN <col> END) "
            "— not UNION. UNION queries are rejected by the query guard."
        ),
    ),
]
