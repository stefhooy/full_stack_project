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

# Human-readable schema description handed to the LLM in its system prompt.
# Slice 2 replaces this hardcoded string with RAG retrieval over per-column
# descriptions — the rest of the agent code doesn't need to change, only how
# this text gets assembled (see src/agent/prompts.py).
GAMES_TABLE_DESCRIPTION = f"""
Table: {GAMES_TABLE}
One row per Steam game (source: SteamSpy).

Columns:
  appid                          BIGINT   Steam app id (primary key)
  name                           VARCHAR  Game title
  developer                      VARCHAR  Developer name(s), comma-separated
  publisher                      VARCHAR  Publisher name(s), comma-separated
  genre                          VARCHAR  Comma-separated genres, e.g. 'Action, Indie'
  languages                      VARCHAR  Comma-separated supported languages
  positive_reviews               INTEGER  Count of positive Steam reviews
  negative_reviews               INTEGER  Count of negative Steam reviews
  review_score                   DOUBLE   positive / (positive + negative), 0..1, NULL if no reviews
  owners_low                     BIGINT   Lower bound of estimated owners
  owners_high                    BIGINT   Upper bound of estimated owners
  average_playtime_forever_min   INTEGER  All-time average playtime, minutes
  average_playtime_2weeks_min    INTEGER  Average playtime in the last 2 weeks, minutes
  price_usd                      DOUBLE   Current price in USD (0 = free-to-play)
  initial_price_usd              DOUBLE   Pre-discount price in USD
  discount_pct                   DOUBLE   Current discount percentage (0-100)
  peak_ccu                       INTEGER  Peak concurrent players yesterday
  ingested_at                    TIMESTAMP  When this row was last refreshed

Notes:
  - Owners are a SteamSpy *estimate range*, not exact. Use (owners_low + owners_high) / 2
    as a midpoint estimate when a single number is needed.
  - Playtime is in minutes; divide by 60 for hours.
  - review_score is a fraction (0..1), not a percentage.
""".strip()
