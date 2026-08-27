"""Ingest games into the local DuckDB catalog from two free, keyless APIs.

Three-step process:
  1. Pull page 0 of SteamSpy's bulk `all` listing (sorted by owners desc) to
     get the appids of the N most-owned games. One request, no rate limit
     concern.
  2. For each of those appids, pull SteamSpy's `appdetails` (owners, reviews,
     genre, playtime) at ~1 request/second.
  3. For the same appid, also pull Steam's own storefront `appdetails`
     (release date, Metacritic score, platforms, categories — see
     src/ingestion/steam_store_client.py for why this is a second, separate
     API rather than something SteamSpy already provides) at ~1 request per
     1.5 seconds.
Every response from both APIs is cached to disk as we go.

Idempotent by construction: responses are cached to data/raw/, and rows are
UPSERTed on appid, so re-running this script after it's already populated
the DB just replays cache hits and re-upserts the same rows — no
duplicates, and it's fast because nothing hits the network again.

Usage:
    python -m src.ingestion.ingest
    python -m src.ingestion.ingest --count 50   # smaller run for a quick test
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from src.config import PROJECT_ROOT, settings
from src.db.connection import get_write_connection
from src.db.schema import CREATE_GAMES_TABLE_SQL
from src.ingestion.steam_store_client import SteamStoreClient
from src.ingestion.steamspy_client import SteamSpyClient

RAW_CACHE_DIR = PROJECT_ROOT / "data" / "raw"

# Steam's real category list runs to ~30 tags per game, heavy with
# controller-model and accessibility variants (DualShock/DualSense
# support, Remote Play on Phone/Tablet/TV, Captions available, ...) that
# don't make interesting analytical questions. This is the subset that
# does — kept short and curated on purpose, not exhaustive; see
# DOCEXP.md's Slice 11 entry for the real category dump this was chosen
# from (Portal 2's actual ~30-tag response).
CATEGORY_ALLOWLIST = [
    "Single-player",
    "Multi-player",
    "Co-op",
    "Online Co-op",
    "PvP",
    "Online PvP",
    "MMO",
    "Steam Achievements",
    "Full controller support",
    "Steam Trading Cards",
    "Steam Workshop",
    "Steam Cloud",
    "VR Only",
    "VR Support",
    "Includes level editor",
]

UPSERT_SQL = """
INSERT INTO games (
    appid, name, developer, publisher, genre, languages,
    positive_reviews, negative_reviews, review_score,
    owners_low, owners_high,
    average_playtime_forever_min, average_playtime_2weeks_min,
    price_usd, initial_price_usd, discount_pct, peak_ccu,
    release_date, release_date_raw, metacritic_score, platforms, categories,
    ingested_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (appid) DO UPDATE SET
    name = EXCLUDED.name,
    developer = EXCLUDED.developer,
    publisher = EXCLUDED.publisher,
    genre = EXCLUDED.genre,
    languages = EXCLUDED.languages,
    positive_reviews = EXCLUDED.positive_reviews,
    negative_reviews = EXCLUDED.negative_reviews,
    review_score = EXCLUDED.review_score,
    owners_low = EXCLUDED.owners_low,
    owners_high = EXCLUDED.owners_high,
    average_playtime_forever_min = EXCLUDED.average_playtime_forever_min,
    average_playtime_2weeks_min = EXCLUDED.average_playtime_2weeks_min,
    price_usd = EXCLUDED.price_usd,
    initial_price_usd = EXCLUDED.initial_price_usd,
    discount_pct = EXCLUDED.discount_pct,
    peak_ccu = EXCLUDED.peak_ccu,
    release_date = EXCLUDED.release_date,
    release_date_raw = EXCLUDED.release_date_raw,
    metacritic_score = EXCLUDED.metacritic_score,
    platforms = EXCLUDED.platforms,
    categories = EXCLUDED.categories,
    ingested_at = EXCLUDED.ingested_at
"""

# Steam's release_date.date has been observed in more than one shape
# depending on the game/region ("18 Apr, 2011", "Apr 18, 2011", a bare
# year). Tried in order; first one that parses wins.
_RELEASE_DATE_FORMATS = ["%d %b, %Y", "%b %d, %Y", "%Y"]


def _parse_release_date(release_date_field: dict[str, Any] | None) -> date | None:
    if not release_date_field or release_date_field.get("coming_soon"):
        return None
    raw = release_date_field.get("date") or ""
    for fmt in _RELEASE_DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_platforms(platforms_field: dict[str, Any] | None) -> str | None:
    if not platforms_field:
        return None
    active = [name for name in ("windows", "mac", "linux") if platforms_field.get(name)]
    return ",".join(active) if active else None


def _parse_categories(categories_field: list[dict[str, Any]] | None) -> str | None:
    if not categories_field:
        return None
    # Dedupe (Steam's own data has real duplicate ids for one description,
    # e.g. two different "Steam Workshop" ids on the same game) and keep
    # only the curated, analytically-interesting subset, in the
    # allowlist's own order rather than whatever order Steam returned.
    present = {c.get("description") for c in categories_field}
    matched = [label for label in CATEGORY_ALLOWLIST if label in present]
    return ",".join(matched) if matched else None


def _parse_owners(owners: str) -> tuple[int | None, int | None]:
    # SteamSpy format: "1,000,000 .. 2,000,000"
    if not owners or ".." not in owners:
        return None, None
    low_str, high_str = owners.split("..")
    try:
        low = int(low_str.replace(",", "").strip())
        high = int(high_str.replace(",", "").strip())
        return low, high
    except ValueError:
        return None, None


def _parse_cents(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return int(value) / 100.0
    except (TypeError, ValueError):
        return None


def _row_from_appdetails(
    details: dict[str, Any], store_data: dict[str, Any] | None = None
) -> tuple | None:
    """`details` is SteamSpy's appdetails response (owners/reviews/genre —
    always required). `store_data` is Steam's own storefront appdetails
    response (release date/Metacritic/platforms/categories) — optional,
    since a game can be missing from one source and not the other; every
    field sourced from it is None when it's unavailable, same as any other
    optional field here."""
    appid = details.get("appid")
    name = details.get("name")
    if appid is None or not name:
        return None

    positive = details.get("positive") or 0
    negative = details.get("negative") or 0
    total_reviews = positive + negative
    review_score = (positive / total_reviews) if total_reviews > 0 else None

    owners_low, owners_high = _parse_owners(details.get("owners", ""))

    store_data = store_data or {}
    release_date_field = store_data.get("release_date")

    return (
        int(appid),
        name,
        details.get("developer") or None,
        details.get("publisher") or None,
        details.get("genre") or None,
        details.get("languages") or None,
        positive,
        negative,
        review_score,
        owners_low,
        owners_high,
        details.get("average_forever"),
        details.get("average_2weeks"),
        _parse_cents(details.get("price")),
        _parse_cents(details.get("initialprice")),
        float(details.get("discount") or 0),
        details.get("ccu"),
        _parse_release_date(release_date_field),
        (release_date_field or {}).get("date") or None,
        (store_data.get("metacritic") or {}).get("score"),
        _parse_platforms(store_data.get("platforms")),
        _parse_categories(store_data.get("categories")),
        datetime.now(timezone.utc),
    )


def run_ingestion(count: int) -> int:
    client = SteamSpyClient(user_agent=settings.steamspy_user_agent, cache_dir=RAW_CACHE_DIR)
    store_client = SteamStoreClient(user_agent=settings.steamspy_user_agent, cache_dir=RAW_CACHE_DIR)

    print(f"[ingest] fetching top-owned games listing (target count: {count})...")
    listing = client.get_all_page(page=0)
    # SteamSpy returns page 0 already ordered by owners descending, so the
    # first `count` entries are the most-owned games — no re-sort needed.
    all_games = list(listing.values())
    target_appids = [g["appid"] for g in all_games[:count]]
    print(f"[ingest] got {len(target_appids)} appids from bulk listing.")

    db_path = settings.duckdb_abs_path
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = get_write_connection(db_path)
    conn.execute(CREATE_GAMES_TABLE_SQL)

    inserted = 0
    for i, appid in enumerate(target_appids, start=1):
        details = client.get_appdetails(appid)
        store_data = store_client.get_appdetails(appid)
        row = _row_from_appdetails(details, store_data)
        if row is None:
            print(f"[ingest]   skip appid={appid}: no usable data")
            continue
        conn.execute(UPSERT_SQL, row)
        inserted += 1
        if i % 25 == 0 or i == len(target_appids):
            print(f"[ingest]   {i}/{len(target_appids)} processed ({inserted} upserted)")

    conn.close()
    print(f"[ingest] done. {inserted} rows upserted into {db_path}")
    return inserted


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest SteamSpy + Steam storefront data into DuckDB."
    )
    parser.add_argument(
        "--count",
        type=int,
        default=settings.ingest_game_count,
        help="Number of top-owned games to ingest (default from INGEST_GAME_COUNT).",
    )
    args = parser.parse_args()
    run_ingestion(args.count)


if __name__ == "__main__":
    sys.exit(main() or 0)
