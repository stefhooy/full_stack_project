"""Thin client for the Steam Web API's live player-count endpoint
(https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/).

No API key required — verified directly against the live endpoint before
building around that assumption. Unlike SteamSpy, this endpoint has no
documented rate limit, but polling ~1/second anyway is the same "be a good
citizen" default used for SteamSpy's appdetails endpoint in
steamspy_client.py — there's no reason to hammer a free public API just
because it doesn't enforce a limit itself.

No response caching here, unlike SteamSpy's client: every call to this
endpoint returns a live, different number by design — caching it would
defeat the entire point of polling.
"""

from __future__ import annotations

import time

import requests

# Side-effect-only import: src/config.py calls truststore.inject_into_ssl()
# at module load time — see the comment there for why it's needed.
import src.config  # noqa: F401

STEAM_WEB_API_URL = (
    "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/"
)
REQUEST_TIMEOUT_SECONDS = 15
MIN_SECONDS_BETWEEN_CALLS = 1.0


class SteamWebClient:
    def __init__(self, user_agent: str):
        self.user_agent = user_agent
        self._last_call: float = 0.0

    def get_current_players(self, appid: int) -> int | None:
        """Returns the live player count, or None if Steam has no data for
        this appid. Two distinct "no data" shapes observed empirically
        against the real endpoint, both treated the same way here: a 200
        response with result != 1 (e.g. a syntactically invalid app id),
        and a 404 (observed for at least one real, currently-delisted app
        id already in the SteamSpy-sourced catalog — Steam's store and
        SteamSpy's index don't always agree on what still exists). Either
        way, one bad app id should skip that game, not abort the whole
        poll run — connection-level failures (timeouts, DNS, 5xx) still
        propagate, since those indicate a real outage worth failing loudly
        on rather than silently producing a mostly-empty snapshot."""
        elapsed = time.monotonic() - self._last_call
        if elapsed < MIN_SECONDS_BETWEEN_CALLS:
            time.sleep(MIN_SECONDS_BETWEEN_CALLS - elapsed)

        resp = requests.get(
            STEAM_WEB_API_URL,
            params={"appid": appid},
            headers={"User-Agent": self.user_agent},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        self._last_call = time.monotonic()

        if resp.status_code == 404:
            return None
        resp.raise_for_status()

        data = resp.json().get("response", {})
        if data.get("result") != 1:
            return None
        return data.get("player_count")
