"""Collection step: poll Steam's live player-count endpoint for every game
in the catalog, write one timestamped JSON snapshot to disk.

Deliberately does NOT touch the DuckDB player_counts table directly — see
build_player_counts_table.py for why. This script's only job is capturing
a moment in time before it's gone; committing the resulting snapshot file
to git is what makes it durable across GitHub Actions' ephemeral runners
(see the Slice 7 DOCEXP entry for the full reasoning).

Usage:
    python -m src.ingestion.poll_player_counts
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.config import PROJECT_ROOT, settings
from src.db.connection import get_read_only_connection
from src.db.schema import GAMES_TABLE
from src.ingestion.steam_web_client import SteamWebClient

SNAPSHOT_DIR = PROJECT_ROOT / "data" / "player_counts_raw"


def run_poll() -> int:
    conn = get_read_only_connection(settings.duckdb_abs_path)
    try:
        appids = [row[0] for row in conn.execute(f"SELECT appid FROM {GAMES_TABLE}").fetchall()]
    finally:
        conn.close()

    print(f"[poll] polling live player counts for {len(appids)} games...")
    client = SteamWebClient(user_agent=settings.steamspy_user_agent)

    polled_at = datetime.now(timezone.utc)
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
