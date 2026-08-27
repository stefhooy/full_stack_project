"""Thin client for Steam's own storefront API
(https://store.steampowered.com/api/appdetails) — distinct from both
SteamSpy (steamspy_client.py, owners/reviews/genre) and the Steam Web API
(steam_web_client.py, live player counts). This one is the same data that
renders an app's actual store page: release date, Metacritic score,
platforms, and categories — none of which SteamSpy's `appdetails` exposes.

No API key required (verified directly: `curl
"https://store.steampowered.com/api/appdetails?appids=620"` returns real
Portal 2 data with no auth). Rate limit is Valve's own stated ~200
requests/5min (≈1 every 1.5s on average) — paced at 1.5s/call here, not the
raw average, to stay clearly under it rather than riding the edge.

Every raw response is cached to disk (data/raw/, `storeapi_<appid>.json` —
a different key prefix than SteamSpy's own `appdetails_<appid>.json` cache
for the same appid, since these are two different APIs' responses for the
same game) — same idempotent-re-run reasoning as steamspy_client.py.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests

# Side-effect-only import: src/config.py calls truststore.inject_into_ssl()
# at module load time — see the comment there for why it's needed.
import src.config  # noqa: F401

STORE_API_URL = "https://store.steampowered.com/api/appdetails"
REQUEST_TIMEOUT_SECONDS = 15
MIN_SECONDS_BETWEEN_CALLS = 1.5


class SteamStoreClient:
    def __init__(self, user_agent: str, cache_dir: Path):
        self.user_agent = user_agent
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_call: float = 0.0

    def _cache_path(self, appid: int) -> Path:
        return self.cache_dir / f"storeapi_{appid}.json"

    def get_appdetails(self, appid: int) -> dict[str, Any] | None:
        """Returns the `data` object for this appid, or None if Steam has
        no store page for it (delisted, region-locked, or a non-game
        listing that 404s/returns success=false) — same "skip this one
        game, don't abort the batch" policy as the other two ingestion
        clients. Connection-level failures (timeouts, DNS, 5xx) still
        propagate."""
        cache_path = self._cache_path(appid)
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
        else:
            elapsed = time.monotonic() - self._last_call
            if elapsed < MIN_SECONDS_BETWEEN_CALLS:
                time.sleep(MIN_SECONDS_BETWEEN_CALLS - elapsed)

            resp = requests.get(
                STORE_API_URL,
                params={"appids": appid},
                headers={"User-Agent": self.user_agent},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            self._last_call = time.monotonic()
            resp.raise_for_status()
            cached = resp.json()
            cache_path.write_text(json.dumps(cached), encoding="utf-8")

        entry = cached.get(str(appid)) or {}
        if not entry.get("success"):
            return None
        return entry.get("data")
