"""Catalog table schema.

This is the only slice-1 table: one row per Steam game, as reported by
SteamSpy. Slice 7 adds a second table (player-count time series); that's why
this file is named schema.py and not games_table.py — it's meant to grow.
"""

GAMES_TABLE = "games"

CREATE_GAMES_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {GAMES_TABLE} (
    appid            BIGINT PRIMARY KEY,
    name              VARCHAR,
    developer         VARCHAR,
    publisher         VARCHAR,
    genre             VARCHAR,
    languages         VARCHAR,
    positive_reviews  INTEGER,
    negative_reviews  INTEGER,
    review_score      DOUBLE,   -- positive / (positive + negative), null if no reviews
    owners_low        BIGINT,   -- lower bound of SteamSpy's owners range estimate
    owners_high       BIGINT,   -- upper bound of SteamSpy's owners range estimate
    average_playtime_forever_min  INTEGER,  -- minutes, all-time average
    average_playtime_2weeks_min   INTEGER,  -- minutes, last 2 weeks average
    price_usd         DOUBLE,   -- current price, dollars (0 = free)
    initial_price_usd DOUBLE,   -- pre-discount price, dollars
    discount_pct      DOUBLE,
    peak_ccu          INTEGER,  -- peak concurrent players yesterday
    ingested_at       TIMESTAMP
);
"""

# Tables the agent's read-only connection is allowed to touch. The SQL guard
# in connection.py checks table references against this list on top of the
# SELECT-only check, so a query can't wander into tables that don't exist yet
# (e.g. a future player_counts table before it's ready for agent use).
ALLOWLISTED_TABLES = {GAMES_TABLE}

# The human-readable description of this table's columns/metrics that used
# to live here as one hardcoded string moved to
# src/agent/rag/schema_corpus.py as of Slice 2 — it's now a list of small,
# independently-embeddable chunks (RAG over the schema) instead of one blob
# always injected whole into the prompt. See that file and
# src/agent/rag/schema_index.py for how it's assembled per-question now.
