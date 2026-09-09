"""Tests for src/agent/graph.py's _render_outliers_fact_block() and
_compose_outliers_answer() -- the structural fix for a real, repeated
hallucination (DOCEXP.md's Slice 58/59 entries): the model naming an
unverified extra "outlier" alongside a real one, confirmed across three
different outlier questions and two separate live runs even after two
rounds of prompt guidance asked it not to.

Rather than trying yet again to convince the model to accurately restate
run_stats's own "outliers" list, these functions make that restatement
the code's job, not the model's: the fact block is rendered directly from
stats_result and the model's own final answer is reduced to short,
name-free commentary. These tests exercise that composition directly,
with no LLM involved -- pure functions of stats_result and a string,
matching this project's `live`-exclusion convention.
"""

from __future__ import annotations

from src.agent.graph import _compose_outliers_answer, _render_outliers_fact_block


def _outliers_result(outliers: list[dict], z_threshold: float = 2.5) -> dict:
    return {"mode": "outliers", "z_threshold": z_threshold, "outliers": outliers}


# --- _render_outliers_fact_block -------------------------------------------


def test_renders_a_real_outlier_by_name_and_z_score():
    result = _outliers_result(
        [{"label": "Counter-Strike: Global Offensive", "value": 1_013_900.0, "z_score": 14.23}]
    )
    block = _render_outliers_fact_block(result)
    assert "Counter-Strike: Global Offensive" in block
    assert "14.23" in block
    assert "2.5" in block  # the threshold itself, for transparency


def test_renders_multiple_real_outliers():
    result = _outliers_result(
        [
            {"label": "Game A", "value": 100.0, "z_score": 3.1},
            {"label": "Game B", "value": 95.0, "z_score": 2.9},
        ]
    )
    block = _render_outliers_fact_block(result)
    assert "Game A" in block
    assert "Game B" in block


def test_renders_an_honest_no_outlier_message_without_naming_anything():
    result = _outliers_result([])
    block = _render_outliers_fact_block(result)
    assert "no value" in block.lower()
    assert "outlier" in block.lower()


# --- _compose_outliers_answer -----------------------------------------------


def test_clean_commentary_with_no_names_passes_through_unchanged():
    result = _outliers_result(
        [{"label": "Counter-Strike: Global Offensive", "value": 1_013_900.0, "z_score": 14.23}]
    )
    commentary = "This means the playerbase is far beyond typical levels for the catalog."
    answer = _compose_outliers_answer(result, commentary, candidate_rows=None)
    assert "Counter-Strike: Global Offensive" in answer  # from the fact block
    assert commentary in answer  # the model's own text, untouched


def test_commentary_naming_an_unauthorized_row_is_replaced_with_a_safe_fallback():
    # The exact real failure this exists to close: PUBG mentioned in the
    # model's own commentary even though only CS:GO is a real outlier.
    result = _outliers_result(
        [{"label": "Counter-Strike: Global Offensive", "value": 1_013_900.0, "z_score": 14.23}]
    )
    commentary = "PUBG: BATTLEGROUNDS also stands out as unusually high."
    candidate_rows = [
        ["Counter-Strike: Global Offensive", 1_013_900.0],
        ["PUBG: BATTLEGROUNDS", 400_000.0],
    ]
    answer = _compose_outliers_answer(result, commentary, candidate_rows)
    assert "PUBG" not in answer
    # The fact block itself must be completely unaffected -- the real
    # outlier is still named, exactly as it should be.
    assert "Counter-Strike: Global Offensive" in answer


def test_commentary_naming_only_the_real_outlier_is_never_flagged():
    # A row appearing in candidate_rows AND being a real, authorized
    # outlier must not trigger the fallback -- only genuinely
    # unauthorized names should.
    result = _outliers_result(
        [{"label": "Counter-Strike: Global Offensive", "value": 1_013_900.0, "z_score": 14.23}]
    )
    commentary = "Counter-Strike: Global Offensive is a clear statistical outlier here."
    candidate_rows = [["Counter-Strike: Global Offensive", 1_013_900.0]]
    answer = _compose_outliers_answer(result, commentary, candidate_rows)
    assert commentary in answer


def test_no_companion_sql_query_means_nothing_to_check_against():
    # candidate_rows is None when the model never ran a companion run_sql
    # query -- nothing to compare against, so commentary passes through.
    result = _outliers_result([])
    commentary = "Nothing here looks unusual."
    answer = _compose_outliers_answer(result, commentary, candidate_rows=None)
    assert commentary in answer
