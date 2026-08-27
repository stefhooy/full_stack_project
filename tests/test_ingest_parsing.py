"""Tests for src/ingestion/ingest.py's parsing functions, including the
Slice 11 Steam-storefront enrichment (release date, Metacritic, platforms,
categories). The fixture data below is the real shape captured from a live
`store.steampowered.com/api/appdetails?appids=620` (Portal 2) response
during development, not invented — including the real duplicate-category
ids Steam's own data actually has (two different ids both labeled "Steam
Workshop").
"""

from __future__ import annotations

from datetime import date

from src.ingestion.ingest import (
    _parse_categories,
    _parse_cents,
    _parse_owners,
    _parse_platforms,
    _parse_release_date,
    _row_from_appdetails,
)

REAL_PORTAL_2_CATEGORIES = [
    {"id": 2, "description": "Single-player"},
    {"id": 1, "description": "Multi-player"},
    {"id": 9, "description": "Co-op"},
    {"id": 38, "description": "Online Co-op"},
    {"id": 22, "description": "Steam Achievements"},
    {"id": 28, "description": "Full controller support"},
    {"id": 29, "description": "Steam Trading Cards"},
    {"id": 51, "description": "Steam Workshop"},
    {"id": 30, "description": "Steam Workshop"},  # real duplicate id, same label
    {"id": 41, "description": "Remote Play on Phone"},  # not in the allowlist
]


def test_parse_release_date_handles_the_real_format():
    assert _parse_release_date({"coming_soon": False, "date": "18 Apr, 2011"}) == date(
        2011, 4, 18
    )


def test_parse_release_date_handles_the_alternate_month_first_format():
    assert _parse_release_date({"coming_soon": False, "date": "Apr 18, 2011"}) == date(
        2011, 4, 18
    )


def test_parse_release_date_returns_none_for_coming_soon():
    assert _parse_release_date({"coming_soon": True, "date": "Q4 2026"}) is None


def test_parse_release_date_returns_none_for_missing_field():
    assert _parse_release_date(None) is None


def test_parse_release_date_returns_none_for_unparseable_text():
    assert _parse_release_date({"coming_soon": False, "date": "sometime, probably"}) is None


def test_parse_platforms_lists_only_the_true_ones():
    assert _parse_platforms({"windows": True, "mac": False, "linux": True}) == "windows,linux"


def test_parse_platforms_returns_none_when_all_false():
    assert _parse_platforms({"windows": False, "mac": False, "linux": False}) is None


def test_parse_platforms_returns_none_for_missing_field():
    assert _parse_platforms(None) is None


def test_parse_categories_dedupes_and_filters_to_the_allowlist():
    result = _parse_categories(REAL_PORTAL_2_CATEGORIES)
    labels = result.split(",")
    assert labels.count("Steam Workshop") == 1  # deduped despite two source ids
    assert "Remote Play on Phone" not in labels  # not in CATEGORY_ALLOWLIST
    assert "Single-player" in labels
    assert "Co-op" in labels


def test_parse_categories_returns_none_when_nothing_matches_the_allowlist():
    assert _parse_categories([{"id": 41, "description": "Remote Play on Phone"}]) is None


def test_parse_owners_range():
    assert _parse_owners("1,000,000 .. 2,000,000") == (1_000_000, 2_000_000)


def test_parse_owners_malformed_returns_none_none():
    assert _parse_owners("unknown") == (None, None)


def test_parse_cents_converts_to_dollars():
    assert _parse_cents(999) == 9.99


def test_parse_cents_none_for_missing():
    assert _parse_cents(None) is None
    assert _parse_cents("") is None


def test_row_from_appdetails_merges_both_sources():
    steamspy_details = {
        "appid": 620,
        "name": "Portal 2",
        "developer": "Valve",
        "publisher": "Valve",
        "genre": "Action, Adventure",
        "languages": "English",
        "positive": 427835,
        "negative": 5675,
        "owners": "5,000,000 .. 10,000,000",
        "average_forever": 0,
        "average_2weeks": 0,
        "price": "999",
        "initialprice": "999",
        "discount": "0",
        "ccu": 1959,
    }
    store_data = {
        "release_date": {"coming_soon": False, "date": "18 Apr, 2011"},
        "metacritic": {"score": 95, "url": "https://example.com"},
        "platforms": {"windows": True, "mac": False, "linux": True},
        "categories": REAL_PORTAL_2_CATEGORIES,
    }
    row = _row_from_appdetails(steamspy_details, store_data)
    assert row[0] == 620
    assert row[1] == "Portal 2"
    # release_date, release_date_raw, metacritic_score, platforms, categories
    assert row[-6] == date(2011, 4, 18)
    assert row[-5] == "18 Apr, 2011"
    assert row[-4] == 95
    assert row[-3] == "windows,linux"
    assert "Single-player" in row[-2]


def test_row_from_appdetails_handles_missing_store_data():
    steamspy_details = {
        "appid": 1,
        "name": "Some Game",
        "positive": 10,
        "negative": 0,
        "owners": "0 .. 20,000",
    }
    row = _row_from_appdetails(steamspy_details, store_data=None)
    assert row[0] == 1
    assert row[-6] is None  # release_date
    assert row[-5] is None  # release_date_raw
    assert row[-4] is None  # metacritic_score
    assert row[-3] is None  # platforms
    assert row[-2] is None  # categories


def test_row_from_appdetails_returns_none_without_a_name():
    assert _row_from_appdetails({"appid": 1, "name": ""}) is None
    assert _row_from_appdetails({"appid": None, "name": "X"}) is None
