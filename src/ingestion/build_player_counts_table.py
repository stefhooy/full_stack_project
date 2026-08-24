"""Materialization step: rebuild the player_counts table from every
committed snapshot under data/player_counts_raw/.

Split from poll_player_counts.py on purpose. GitHub Actions runners are
ephemeral — nothing written to a local DuckDB file during a scheduled run
would survive to the next one. So the poller's only job is capturing a
snapshot and committing it to git (durable, tiny, diffable); building the
actual queryable table from the *full accumulated history* of snapshots is
a separate, idempotent, rerun-anytime step — the same
collect-raw-then-build split already used for the SteamSpy catalog
(steamspy_client.py caches to disk, ingest.py builds the table from it).
Run this locally after `git pull`, or as a Docker build step so a freshly
deployed backend has the full history baked in (see the Dockerfile).

Idempotent: ON CONFLICT (appid, polled_at) DO NOTHING, so re-running over
snapshots already loaded is a safe no-op, not a duplicate-rows problem.

Usage:
    python -m src.ingestion.build_player_counts_table
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from src.config import PROJECT_ROOT, settings
from src.db.connection import get_write_connection
from src.db.schema import CREATE_PLAYER_COUNTS_TABLE_SQL

SNAPSHOT_DIR = PROJECT_ROOT / "data" / "player_counts_raw"

UPSERT_SQL = """
INSERT INTO player_counts (appid, player_count, polled_at)
VALUES (?, ?, ?)
ON CONFLICT (appid, polled_at) DO NOTHING
"""


def run_build() -> int:
    if not SNAPSHOT_DIR.exists():
        print(f"[build] no snapshots yet at {SNAPSHOT_DIR}, nothing to build")
        return 0

    snapshot_files = sorted(SNAPSHOT_DIR.glob("*.json"))
    if not snapshot_files:
        print(f"[build] no snapshot files in {SNAPSHOT_DIR}, nothing to build")
        return 0

    conn = get_write_connection(settings.duckdb_abs_path)
    conn.execute(CREATE_PLAYER_COUNTS_TABLE_SQL)

    rows_inserted = 0
    for path in snapshot_files:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        polled_at = datetime.fromisoformat(snapshot["polled_at"])
        rows = [
            (int(appid), count, polled_at) for appid, count in snapshot["counts"].items()
        ]
        conn.executemany(UPSERT_SQL, rows)
        rows_inserted += len(rows)

    total = conn.execute("SELECT COUNT(*) FROM player_counts").fetchone()[0]
    conn.close()
    print(
        f"[build] processed {len(snapshot_files)} snapshot(s), "
        f"{rows_inserted} rows considered, {total} total rows in player_counts"
    )
    return total


if __name__ == "__main__":
    sys.exit(0 if run_build() >= 0 else 1)
