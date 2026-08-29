"""Collection step: poll Steam's live player-count endpoint for every game
in the catalog, write one timestamped JSON snapshot to disk.

Deliberately does NOT touch the DuckDB player_counts table directly — see
build_player_counts_table.py for why. This script's only job is capturing
a moment in time before it's gone; committing the resulting snapshot file
to git is what makes it durable across GitHub Actions' ephemeral runners
(see the Slice 7 DOCEXP entry for the full reasoning).

Gets its appid list from SteamSpy's own cheap bulk listing directly
(SteamSpyClient.get_all_page — one request, no per-game rate limit),
not from a pre-built `games` table. Slice 29 removed that dependency
after `poll_player_counts.yml`'s "rebuild the catalog first" step (the
*full* ingest.py, including both APIs' per-game enrichment loops) turned
out to cost ~40 real minutes every 6 hours just to learn appids this
script never used any other field of — see DOCEXP.md's Slice 29 entry.

Usage:
    python -m src.ingestion.poll_player_counts
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

from src.config import PROJECT_ROOT, settings
from src.ingestion.steam_web_client import SteamWebClient
from src.ingestion.steamspy_client import SteamSpyClient

SNAPSHOT_DIR = PROJECT_ROOT / "data" / "player_counts_raw"
RAW_CACHE_DIR = PROJECT_ROOT / "data" / "raw"


def _fetch_target_appids(count: int) -> list[int]:
    """Just the appids of the top-owned `count` games — the cheap first
    step of ingest.py's three-step process, without the two per-game
    enrichment loops that follow it there (this script has no use for
    genre, release date, Metacritic, or any of the rest)."""
    client = SteamSpyClient(user_agent=settings.steamspy_user_agent, cache_dir=RAW_CACHE_DIR)
    listing = client.get_all_page(page=0)
    all_games = list(listing.values())
    return [g["appid"] for g in all_games[:count]]


def run_poll() -> int:
    appids = _fetch_target_appids(settings.ingest_game_count)

    print(f"[poll] polling live player counts for {len(appids)} games...")
    client = SteamWebClient(user_agent=settings.steamspy_user_agent)

    polled_at = datetime.now(UTC)
    counts: dict[str, int] = {}
    for i, appid in enumerate(appids, start=1):
        count = client.get_current_players(appid)
        if count is not None:
            counts[str(appid)] = count
        if i % 25 == 0 or i == len(appids):
            print(f"[poll]   {i}/{len(appids)} polled ({len(counts)} with data)")

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_path = SNAPSHOT_DIR / f"{polled_at.strftime('%Y-%m-%dT%H-%M-%SZ')}.json"
    snapshot_path.write_text(
        json.dumps({"polled_at": polled_at.isoformat(), "counts": counts}, indent=2),
        encoding="utf-8",
    )
    print(f"[poll] wrote {snapshot_path} ({len(counts)} games)")
    return len(counts)


if __name__ == "__main__":
    sys.exit(0 if run_poll() >= 0 else 1)
