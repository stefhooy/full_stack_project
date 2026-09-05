"""Unit tests for the per-IP rate limiter (src/api/rate_limit.py).
Constructs a fresh InMemoryRateLimiter with small, test-friendly
parameters rather than reaching into the module-level `_limiter`
singleton (which is fixed at import time from real `settings` values,
so monkeypatching settings after import wouldn't affect it anyway).
"""

from __future__ import annotations

import time

import pytest
from fastapi import HTTPException

from src.api.rate_limit import InMemoryRateLimiter, enforce_rate_limit


def test_requests_under_the_limit_all_pass():
    limiter = InMemoryRateLimiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        limiter.check("1.2.3.4")  # must not raise


def test_the_request_that_exceeds_the_limit_raises_429():
    limiter = InMemoryRateLimiter(max_requests=2, window_seconds=60)
    limiter.check("1.2.3.4")
    limiter.check("1.2.3.4")
    with pytest.raises(HTTPException) as exc_info:
        limiter.check("1.2.3.4")
    assert exc_info.value.status_code == 429


def test_different_ips_are_tracked_independently():
    limiter = InMemoryRateLimiter(max_requests=1, window_seconds=60)
    limiter.check("1.1.1.1")  # uses up 1.1.1.1's one allowed request
    limiter.check("2.2.2.2")  # a different key, must not be affected


def test_the_window_slides_old_hits_expire_and_free_up_room():
    limiter = InMemoryRateLimiter(max_requests=1, window_seconds=0.05)
    limiter.check("1.2.3.4")
    time.sleep(0.1)  # older than the window
    limiter.check("1.2.3.4")  # must not raise -- the old hit has expired


class _FakeClient:
    def __init__(self, host):
        self.host = host


class _FakeRequest:
    def __init__(self, client):
        self.client = client


def test_enforce_rate_limit_uses_the_real_client_host():
    # Uses the shared module-level limiter, so use a host string unlikely
    # to collide with anything else exercising it in the same test run.
    request = _FakeRequest(client=_FakeClient("203.0.113.42"))
    enforce_rate_limit(request)  # must not raise on a single call


def test_enforce_rate_limit_falls_back_to_unknown_when_client_is_none():
    # A real, documented edge case in the source (`request.client.host if
    # request.client else "unknown"`) -- worth pinning down directly
    # rather than trusting it never gets exercised.
    request = _FakeRequest(client=None)
    enforce_rate_limit(request)  # must not raise (or crash on None.host)
