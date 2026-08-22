"""Thin client for the SteamSpy API (https://steamspy.com/api.php).

Two endpoints are used:
  - request=all&page=N   : bulk list, ~1000 games/page, sorted by owners desc.
                            Cheap, but no genre/languages/tags.
  - request=appdetails&appid=X : per-game detail incl. genre/languages/tags.
                            SteamSpy asks for ~1 request/second on this one.

Every raw response is cached to disk (data/raw/) keyed by request, so a
re-run of ingestion doesn't re-hit the network for games it already has —
that's what makes ingest.py idempotent and safe to re-run.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests
import truststore

# Some environments (notably Windows machines with AV software like Avast
# doing TLS interception) re-sign HTTPS traffic with a locally-installed
# root CA that Windows trusts but Python's bundled `certifi` CA list does
# not, causing SSLCertVerificationError on every request. truststore makes
# the stdlib ssl module use the OS trust store directly instead of
# certifi's, which is the correct fix (not disabling verification).
truststore.inject_into_ssl()

STEAMSPY_BASE_URL = "https://steamspy.com/api.php"
REQUEST_TIMEOUT_SECONDS = 15
MIN_SECONDS_BETWEEN_APPDETAILS_CALLS = 1.0


class SteamSpyClient:
    def __init__(self, user_agent: str, cache_dir: Path):
        self.user_agent = user_agent
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._last_appdetails_call: float = 0.0

    def _get(self, params: dict[str, Any]) -> Any:
        resp = requests.get(
            STEAMSPY_BASE_URL,
            params=params,
            headers={"User-Agent": self.user_agent},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        return resp.json()

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    def _read_cache(self, key: str) -> Any | None:
        path = self._cache_path(key)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        return None

    def _write_cache(self, key: str, data: Any) -> None:
        self._cache_path(key).write_text(json.dumps(data), encoding="utf-8")

    def get_all_page(self, page: int) -> dict[str, Any]:
        """Bulk listing page. Cached — re-running ingestion won't re-fetch
        a page it already has on disk."""
        cache_key = f"all_page_{page}"
        cached = self._read_cache(cache_key)
        if cached is not None:
            return cached
        data = self._get({"request": "all", "page": page})
        self._write_cache(cache_key, data)
        return data

    def get_appdetails(self, appid: int) -> dict[str, Any]:
        """Per-game detail (genre/languages/tags). Cached per appid, and
        rate-limited to ~1 req/sec against the network — a cache hit skips
        the wait entirely, which is what makes re-running ingestion fast."""
        cache_key = f"appdetails_{appid}"
        cached = self._read_cache(cache_key)
        if cached is not None:
            return cached

        elapsed = time.monotonic() - self._last_appdetails_call
        if elapsed < MIN_SECONDS_BETWEEN_APPDETAILS_CALLS:
            time.sleep(MIN_SECONDS_BETWEEN_APPDETAILS_CALLS - elapsed)

        data = self._get({"request": "appdetails", "appid": appid})
        self._last_appdetails_call = time.monotonic()
        self._write_cache(cache_key, data)
        return data
