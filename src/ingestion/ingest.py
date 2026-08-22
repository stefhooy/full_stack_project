"""Ingest a few hundred games from SteamSpy into the local DuckDB catalog.

Two-step process:
  1. Pull page 0 of the bulk `all` listing (sorted by owners desc) to get the
     appids of the N most-owned games. One request, no rate limit concern.
  2. For each of those appids, pull `appdetails` (genre/languages) at ~1
     request/second, caching every response to disk as we go.

Idempotent by construction: SteamSpy responses are cached to data/raw/, and
rows are UPSERTed on appid, so re-running this script after it's already
populated the DB just replays cache hits and re-upserts the same rows —
no duplicates, and it's fast because nothing hits the network again.

Usage:
    python -m src.ingestion.ingest
    python -m src.ingestion.ingest --count 50   # smaller run for a quick test
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import PROJECT_ROOT, settings
from src.db.connection import get_write_connection
from src.db.schema import CREATE_GAMES_TABLE_SQL
from src.ingestion.steamspy_client import SteamSpyClient

RAW_CACHE_DIR = PROJECT_ROOT / "data" / "raw"

UPSERT_SQL = """
INSERT INTO games (
    appid, name, developer, publisher, genre, languages,
    positive_reviews, negative_reviews, review_score,
    owners_low, owners_high,
    average_playtime_forever_min, average_playtime_2weeks_min,
    price_usd, initial_price_usd, discount_pct, peak_ccu, ingested_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    ingested_at = EXCLUDED.ingested_at
"""


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


def _row_from_appdetails(details: dict[str, Any]) -> tuple | None:
    appid = details.get("appid")
    name = details.get("name")
    if appid is None or not name:
        return None

    positive = details.get("positive") or 0
    negative = details.get("negative") or 0
    total_reviews = positive + negative
    review_score = (positive / total_reviews) if total_reviews > 0 else None

    owners_low, owners_high = _parse_owners(details.get("owners", ""))

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
        datetime.now(timezone.utc),
    )


def run_ingestion(count: int) -> int:
    client = SteamSpyClient(user_agent=settings.steamspy_user_agent, cache_dir=RAW_CACHE_DIR)

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
        row = _row_from_appdetails(details)
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
    parser = argparse.ArgumentParser(description="Ingest SteamSpy data into DuckDB.")
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
