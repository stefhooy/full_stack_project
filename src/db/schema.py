"""DB table schema.

Two tables: `games` (the SteamSpy catalog, Slice 1) and `player_counts`
(a real time series, Slice 7) — that's why this file is named schema.py
and not games_table.py, it was always meant to grow.

The two tables have fundamentally different freshness semantics, which is
why they're ingested differently (see src/ingestion/):
  - `games` reflects SteamSpy's *current* state. Re-fetching always
    overwrites what we know — there's no historical value in an old
    snapshot, so it's rebuilt fresh (UPSERT) each ingestion run.
  - `player_counts` is genuinely historical: Steam's live API has no
    history endpoint, so each poll captures a moment that can never be
    recovered later. Rows accumulate; nothing is ever overwritten.
"""

GAMES_TABLE = "games"
PLAYER_COUNTS_TABLE = "player_counts"

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
    -- Slice 11: Steam's own storefront API (store.steampowered.com/api/appdetails),
    -- not SteamSpy — see src/ingestion/steam_store_client.py. Fills gaps SteamSpy
    -- never had: release date, critic score, platform/feature breadth.
    release_date      DATE,     -- parsed from Steam's "DD Mon, YYYY"-ish string; null if
                                 -- unparseable or the game was "coming soon" at ingest time
    release_date_raw  VARCHAR,  -- the original string, kept even when parsing fails
    metacritic_score  INTEGER,  -- 0-100; null for the many games Metacritic never scored
    platforms         VARCHAR,  -- comma-joined subset of windows/mac/linux that are true
    categories        VARCHAR,  -- comma-joined, curated subset of Steam's ~30 raw category
                                 -- tags (see ingest.py's CATEGORY_ALLOWLIST) -- the full raw
                                 -- list is mostly controller/accessibility noise
    ingested_at       TIMESTAMP
);
"""

CREATE_PLAYER_COUNTS_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {PLAYER_COUNTS_TABLE} (
    appid         BIGINT,
    player_count  INTEGER,   -- live concurrent players at polled_at, per Steam Web API
    polled_at     TIMESTAMP,
    PRIMARY KEY (appid, polled_at)
);
"""

# Tables the agent's read-only connection is allowed to touch. The SQL guard
# in connection.py checks table references against this list on top of the
# SELECT-only check, so a query can't wander into tables that don't exist yet.
ALLOWLISTED_TABLES = {GAMES_TABLE, PLAYER_COUNTS_TABLE}

# The human-readable description of this table's columns/metrics that used
# to live here as one hardcoded string moved to
# src/agent/rag/schema_corpus.py as of Slice 2 — it's now a list of small,
# independently-embeddable chunks (RAG over the schema) instead of one blob
# always injected whole into the prompt. See that file and
# src/agent/rag/schema_index.py for how it's assembled per-question now.
