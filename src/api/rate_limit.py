"""Per-IP rate limiting: an in-memory sliding window, no Redis or other
external store needed.

That's a real constraint, not a shortcut we forgot to fix: the Slice 6
deployment decision (see DOCEXP.md) is a single, normal long-running
Python process on a free host, not horizontally-scaled serverless — so
in-memory state is coherent for the whole deployment as long as it stays
that way. Scaling to multiple backend instances would need a shared store
(Redis) for this to keep working correctly; noted as an open question
rather than solved speculatively before it's needed.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from src.config import settings


class InMemoryRateLimiter:
    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        hits = self._hits[key]
        while hits and now - hits[0] > self.window_seconds:
            hits.popleft()
        if len(hits) >= self.max_requests:
            raise HTTPException(
                status_code=429,
                detail="Too many requests — please slow down and try again shortly.",
            )
        hits.append(now)


_limiter = InMemoryRateLimiter(
    max_requests=settings.rate_limit_max_requests,
    window_seconds=settings.rate_limit_window_seconds,
)


def enforce_rate_limit(request: Request) -> None:
    """FastAPI dependency — raises 429 if this client IP is over the limit.
    Uses request.client.host directly; a deployment behind a reverse proxy
    would need to trust X-Forwarded-For instead, which is a proxy-specific
    trust decision left to the deployment slice, not hardcoded here."""
    client_ip = request.client.host if request.client else "unknown"
    _limiter.check(client_ip)
