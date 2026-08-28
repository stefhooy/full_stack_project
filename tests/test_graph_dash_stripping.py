"""Tests for src/agent/graph.py's _strip_dashes(), the deterministic
guarantee behind "no em dashes or en dashes anywhere on the site" (the
system prompt also asks the model not to use them, but that's a request,
not a guarantee -- this is the actual backstop, added after a real answer
came back from the live model with a dash despite the prompt rule).
"""

from __future__ import annotations

from src.agent.graph import _strip_dashes


def test_a_spaced_em_dash_aside_becomes_a_comma():
    # The real case that motivated this: the model's own answer came back
    # as "Aseprite – review score...", a spaced dash used as a
    # parenthetical aside -- a comma reads naturally in that position.
    result = _strip_dashes("Aseprite – review score is 0.991")
    assert "–" not in result
    assert "—" not in result
    assert result == "Aseprite, review score is 0.991"


def test_a_spaced_em_dash_also_becomes_a_comma():
    result = _strip_dashes("Bold term — the explanation")
    assert result == "Bold term, the explanation"


def test_a_tight_numeric_range_keeps_its_meaning_as_a_hyphen():
    # A bare dash with no surrounding space is almost always a range
    # ("10-20"), not a parenthetical -- turning it into a comma would
    # silently change a range into what reads like a list of two numbers.
    result = _strip_dashes("A range like 10–20 items")
    assert result == "A range like 10-20 items"


def test_a_compound_word_hyphen_is_left_alone():
    # A plain ASCII hyphen was never the target -- only the real em/en
    # dash characters get rewritten.
    result = _strip_dashes("self-collected dataset stays fine")
    assert result == "self-collected dataset stays fine"


def test_text_with_no_dashes_is_unchanged():
    result = _strip_dashes("Portal 2 has a review score of 0.987.")
    assert result == "Portal 2 has a review score of 0.987."


def test_multiple_dashes_in_one_answer_all_get_stripped():
    result = _strip_dashes("Aseprite – 0.991\nHoloCure – 0.990")
    assert "–" not in result
    assert result == "Aseprite, 0.991\nHoloCure, 0.990"


def test_non_breaking_hyphen_is_normalized_too():
    # A real one, found in an actual live answer ("highest‑rated") --
    # not literally an em/en dash, but the same "unusual punctuation mark"
    # problem this whole function exists to guarantee against.
    result = _strip_dashes("the highest‑rated games")
    assert "‑" not in result
    assert result == "the highest-rated games"
