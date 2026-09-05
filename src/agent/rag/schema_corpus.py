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

Adding a table (player_counts, added in Slice 7) or a new metric note
means appending chunks here, not rewriting a paragraph — exactly what
happened when player_counts landed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.db.schema import GAMES_TABLE, PLAYER_COUNTS_TABLE


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


SCHEMA_CHUNKS: list[SchemaChunk] = [
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
        text=(
            f"Column {GAMES_TABLE}.name: VARCHAR. Game title. A plain "
            "`name ILIKE '%<phrase>%'` is a literal substring match and breaks "
            "on punctuation the user didn't type exactly, e.g. 'Counter Strike' "
            "(a space) will NOT match the real title 'Counter-Strike: Global "
            "Offensive' (a hyphen and colon) at all, real, confirmed bug. "
            "Normalize both sides first: "
            "regexp_replace(name, '[-:]', ' ', 'g') ILIKE '%<phrase with "
            "punctuation removed the same way>%'. That alone can still return "
            "several real, differently-named games (e.g. 'Counter-Strike', "
            "'Counter-Strike: Source', 'Counter-Strike: Global Offensive' are "
            "three separate rows) — when a query needs exactly one, disambiguate "
            "by the one actually being asked about in practice: "
            "ORDER BY peak_ccu DESC LIMIT 1 picks the currently-relevant game "
            "a user almost always means, not an old or minor variant. Write the "
            "query argument as a plain string value, with the single quotes SQL "
            "needs left bare: JSON never requires a backslash before a single "
            "quote (only before a double quote or a backslash itself), so "
            "backslash-escaping one anyway produces invalid JSON, a real, "
            "confirmed way this exact tool call has failed before, not a "
            "hypothetical one."
        ),
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
    # --- Slice 11: Steam's own storefront API (store.steampowered.com/api/
    # appdetails), not SteamSpy — fills gaps SteamSpy never had.
    SchemaChunk(
        id="column:release_date",
        kind="column",
        text=(
            f"Column {GAMES_TABLE}.release_date: DATE. When the game released. NULL if the "
            "game was still 'coming soon' when this catalog was last refreshed, or if "
            "Steam's date string for it couldn't be parsed into a real date — see "
            "release_date_raw for the original text in that case."
        ),
    ),
    SchemaChunk(
        id="column:release_date_raw",
        kind="column",
        text=(
            f"Column {GAMES_TABLE}.release_date_raw: VARCHAR. The original release-date "
            "text from Steam, kept even when release_date couldn't be parsed from it."
        ),
    ),
    SchemaChunk(
        id="column:metacritic_score",
        kind="column",
        text=(
            f"Column {GAMES_TABLE}.metacritic_score: INTEGER, 0-100. Metacritic's critic "
            "score. NULL for the many games Metacritic never scored (most indie titles) — "
            "NULL here means 'not scored', not 'scored zero'; don't treat it as 0 in "
            "aggregates or exclude it silently without noting why."
        ),
    ),
    SchemaChunk(
        id="column:platforms",
        kind="column",
        text=(
            f"Column {GAMES_TABLE}.platforms: VARCHAR. Comma-separated subset of "
            "windows, mac, linux the game supports. Match with LIKE '%mac%' etc., not '='."
        ),
    ),
    SchemaChunk(
        id="column:categories",
        kind="column",
        text=(
            f"Column {GAMES_TABLE}.categories: VARCHAR. Comma-separated feature tags "
            "(e.g. 'Single-player, Co-op, Steam Achievements, Steam Workshop'). A curated "
            "subset of Steam's real category list, not exhaustive — match with LIKE "
            "'%Co-op%' etc., not '='."
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
            "UNION queries are rejected by the query guard. To get two different "
            "aggregates side by side in one row, use conditional aggregation instead, "
            "e.g. COUNT(CASE WHEN <condition> THEN 1 END) AS <label>. For a real group "
            "comparison — e.g. Action games vs. free-to-play games — use run_stats's "
            "compare_two_groups mode instead of hand-rolling it with conditional "
            "aggregation."
        ),
    ),
    # --- player_counts (Slice 7): a real time series, not a snapshot table.
    # Every row is a historical fact that can never be re-fetched (Steam's
    # live API has no history endpoint) — contrast with `games`, which is
    # always current state and gets overwritten on each ingest.
    SchemaChunk(
        id="table:player_counts",
        kind="table",
        text=(
            f"Table: {PLAYER_COUNTS_TABLE}. A time series: one row per game per poll, "
            "recording how many people were playing it at that moment (source: Steam Web "
            "API's live player-count endpoint). Polled periodically, not continuously — "
            "gaps between polls are normal, not missing data."
        ),
        always_include=True,
    ),
    SchemaChunk(
        id="column:player_counts.appid",
        kind="column",
        text=(
            f"Column {PLAYER_COUNTS_TABLE}.appid: BIGINT. Steam app id — join to "
            f"{GAMES_TABLE}.appid to get the game's name and other catalog facts."
        ),
    ),
    SchemaChunk(
        id="column:player_counts.player_count",
        kind="column",
        text=(
            f"Column {PLAYER_COUNTS_TABLE}.player_count: INTEGER. Live concurrent players "
            "at the moment of polling — how many people were playing right then, not a "
            "daily total or a unique-player count."
        ),
    ),
    SchemaChunk(
        id="column:player_counts.polled_at",
        kind="column",
        text=(
            f"Column {PLAYER_COUNTS_TABLE}.polled_at: TIMESTAMP. When this reading was "
            "taken. Order by this column for a trend over time; group by a truncated "
            "version of it (e.g. date_trunc('day', polled_at)) for daily aggregates."
        ),
    ),
    SchemaChunk(
        id="metric:player_counts_is_a_join",
        kind="metric_note",
        text=(
            f"A question naming a specific game and asking about its player count over "
            f"time needs a JOIN between {PLAYER_COUNTS_TABLE} and {GAMES_TABLE} on appid "
            f"(to filter by name) — {PLAYER_COUNTS_TABLE} alone has no game name column."
        ),
    ),
    SchemaChunk(
        id="metric:peak_ccu_vs_player_counts",
        kind="metric_note",
        text=(
            f"Two different columns both relate to 'concurrent players' — pick the right "
            f"one, don't confuse them: {GAMES_TABLE}.peak_ccu is a single number (peak "
            f"concurrent players on the day the catalog was last refreshed), part of the "
            f"{GAMES_TABLE} table. {PLAYER_COUNTS_TABLE}.player_count is a live reading "
            f"from a separate time-series table ({PLAYER_COUNTS_TABLE}), one row per poll — "
            f"use this one for 'right now' or 'over time' questions, and remember it "
            f"requires joining to {GAMES_TABLE} to filter by name (see the join note)."
        ),
    ),
]
