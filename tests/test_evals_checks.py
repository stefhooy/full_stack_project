"""Unit tests for the deterministic check builders (src/evals/checks.py) and
the one check with a real incident behind it
(_check_action_vs_f2p_not_mislabeled, src/evals/golden_questions.py).

This file exists specifically because one didn't: Slice 30's whole saga
(a wrong check failing the same golden question across four separate
slices before the check itself, not the model, was found to be the bug)
happened because nothing asserted these functions' own correctness in
isolation -- every prior verification ran the check *through* a real
LLM call, which meant a bug in the check's own logic and a bug in the
model's own answer were indistinguishable from the outside. These tests
construct AgentResult directly (no LLM, no DuckDB, no network) so the
check logic itself is pinned down independently of anything upstream of
it -- see DOCEXP.md's Slice 42 entry for the audit finding this closes.
"""

from __future__ import annotations

from src.agent.graph import AgentResult
from src.evals.checks import (
    all_of,
    contains_number,
    contains_text,
    forecast_has_real_projection,
    forecast_reports_insufficient_history,
    no_data_fabricated,
    route_is,
)
from src.evals.golden_questions import _check_action_vs_f2p_not_mislabeled


def _result(**overrides) -> AgentResult:
    defaults = dict(
        answer="",
        sql=None,
        columns=None,
        rows=None,
        stats_query=None,
        stats_result=None,
        forecast_query=None,
        forecast_result=None,
        retrieved_chunk_ids=None,
        route=None,
        chart_spec=None,
        attempts=1,
        tool_errors=0,
        total_tokens=0,
        estimated_cost_usd=0.0,
    )
    defaults.update(overrides)
    return AgentResult(**defaults)


# --- contains_number ---------------------------------------------------


def test_contains_number_passes_within_relative_tolerance():
    check = contains_number(1000.0, tolerance=0.05, rel=True)
    result = _result(answer="There are about 1,020 games in that category.")
    assert check(result).passed


def test_contains_number_fails_outside_relative_tolerance():
    check = contains_number(1000.0, tolerance=0.05, rel=True)
    result = _result(answer="There are about 1,200 games in that category.")
    assert not check(result).passed


def test_contains_number_absolute_tolerance_for_small_expected_values():
    # rel=True with expected=0 would make the tolerance meaninglessly
    # tight (0.05 * 0 == 0) -- this is exactly why rel=False exists.
    check = contains_number(0.0, tolerance=0.5, rel=False)
    result = _result(answer="The mean price is $0.00.")
    assert check(result).passed


def test_contains_number_finds_no_number_at_all():
    check = contains_number(42.0)
    result = _result(answer="I could not compute that.")
    assert not check(result).passed


# --- contains_text -------------------------------------------------------


def test_contains_text_is_case_insensitive():
    check = contains_text("Counter-Strike")
    result = _result(answer="the top game is counter-strike: global offensive")
    assert check(result).passed


def test_contains_text_fails_when_absent():
    check = contains_text("Portal 2")
    result = _result(answer="the top game is Counter-Strike: Global Offensive")
    assert not check(result).passed


def test_contains_text_matches_across_typographic_spacing():
    # Real, observed failure (Slice 44): the model rendered a brand name
    # using narrow no-break spaces (U+202F) between words instead of plain
    # ASCII spaces, a factually correct answer a plain substring check
    # missed. Built with chr(0x202F) rather than a literal character in
    # this source file, so the character stays unambiguous to ruff/editors.
    nnbsp = chr(0x202F)
    stylized_name = nnbsp.join(["EA", "SPORTS", "FC", "24"])
    check = contains_text("EA SPORTS FC 24")
    result = _result(answer=f"the outlier is {stylized_name} at $69.99")
    assert check(result).passed


# --- route_is --------------------------------------------------------------


def test_route_is_matches_exact_route():
    assert route_is("lookup")(_result(route="lookup")).passed


def test_route_is_fails_on_mismatch():
    assert not route_is("lookup")(_result(route="analysis")).passed


# --- no_data_fabricated ------------------------------------------------


def test_no_data_fabricated_passes_when_both_are_none():
    check = no_data_fabricated()
    assert check(_result(sql=None, stats_result=None)).passed


def test_no_data_fabricated_fails_if_sql_was_run():
    check = no_data_fabricated()
    assert not check(_result(sql="SELECT 1", stats_result=None)).passed


def test_no_data_fabricated_fails_if_stats_were_computed():
    check = no_data_fabricated()
    assert not check(_result(sql=None, stats_result={"mode": "outliers"})).passed


# --- all_of --------------------------------------------------------------


def test_all_of_passes_only_when_every_sub_check_passes():
    check = all_of(route_is("lookup"), contains_text("Portal"))
    passing = _result(route="lookup", answer="Portal 2 is great")
    failing_route = _result(route="analysis", answer="Portal 2 is great")
    failing_text = _result(route="lookup", answer="something else")
    assert check(passing).passed
    assert not check(failing_route).passed
    assert not check(failing_text).passed


def test_all_of_concatenates_every_sub_check_detail():
    check = all_of(route_is("lookup"), route_is("lookup"))
    detail = check(_result(route="analysis")).detail
    assert detail.count("expected route=") == 2


# --- _check_action_vs_f2p_not_mislabeled ---------------------------------
# The actual check behind Slice 4's original bug and Slice 30's discovery
# that the check itself, not the model, was wrong for four straight
# slices. Every branch below is a real path this check has to get right.


def test_f2p_check_passes_via_compare_two_groups_with_a_real_zero_mean():
    result = _result(
        stats_result={
            "mode": "compare_two_groups",
            "group_a": "Action",
            "mean_a": 18.5,
            "group_b": "free-to-play",
            "mean_b": 0.0,
        }
    )
    outcome = _check_action_vs_f2p_not_mislabeled(result)
    assert outcome.passed


def test_f2p_check_fails_via_compare_two_groups_when_mean_is_not_zero():
    # This is the literal Slice 4 bug: a group labeled free-to-play whose
    # real mean price is nonzero, proving it wasn't actually filtered on
    # price_usd = 0.
    result = _result(
        stats_result={
            "mode": "compare_two_groups",
            "group_a": "Action",
            "mean_a": 18.5,
            "group_b": "free-to-play",
            "mean_b": 12.3,
        }
    )
    outcome = _check_action_vs_f2p_not_mislabeled(result)
    assert not outcome.passed
    assert "mislabeled" in outcome.detail


def test_f2p_check_fails_via_compare_two_groups_with_no_f2p_group_at_all():
    result = _result(
        stats_result={
            "mode": "compare_two_groups",
            "group_a": "Action",
            "mean_a": 18.5,
            "group_b": "Strategy",
            "mean_b": 22.0,
        }
    )
    outcome = _check_action_vs_f2p_not_mislabeled(result)
    assert not outcome.passed
    assert "no group labeled free-to-play" in outcome.detail


def test_f2p_check_passes_via_plain_sql_with_a_real_zero_value():
    # This is the exact case Slice 30 found the *original* check
    # incorrectly rejecting for three straight slices: a genuinely
    # correct plain-SQL answer, marked wrong only because it didn't use
    # run_stats.
    result = _result(
        columns=["avg_action_price", "avg_freetoplay_price"],
        rows=[[18.5, 0.0]],
    )
    outcome = _check_action_vs_f2p_not_mislabeled(result)
    assert outcome.passed
    assert "plain SQL" in outcome.detail


def test_f2p_check_fails_via_plain_sql_when_the_value_is_not_zero():
    result = _result(
        columns=["avg_action_price", "avg_freetoplay_price"],
        rows=[[18.5, 9.99]],
    )
    outcome = _check_action_vs_f2p_not_mislabeled(result)
    assert not outcome.passed
    assert "mislabeled" in outcome.detail


def test_f2p_check_fails_cleanly_when_neither_real_path_is_present():
    result = _result(sql="SELECT 1", columns=None, rows=None, stats_result=None)
    outcome = _check_action_vs_f2p_not_mislabeled(result)
    assert not outcome.passed
    assert "expected either" in outcome.detail


# --- forecast_has_real_projection / forecast_reports_insufficient_history ---


def test_forecast_has_real_projection_passes_on_a_real_projection():
    check = forecast_has_real_projection()
    result = _result(forecast_result={"insufficient_history": False, "projected_value": 1000.0})
    assert check(result).passed


def test_forecast_has_real_projection_fails_when_history_was_insufficient():
    check = forecast_has_real_projection()
    result = _result(forecast_result={"insufficient_history": True})
    assert not check(result).passed


def test_forecast_has_real_projection_fails_when_the_tool_was_never_called():
    check = forecast_has_real_projection()
    result = _result(forecast_result=None)
    assert not check(result).passed


def test_forecast_reports_insufficient_history_passes_on_the_honest_degradation():
    check = forecast_reports_insufficient_history()
    result = _result(forecast_result={"insufficient_history": True, "n_snapshots": 0})
    assert check(result).passed


def test_forecast_reports_insufficient_history_fails_on_a_real_projection():
    # The inverse case matters just as much: a check that always passes
    # regardless of the flag's actual value would be worthless.
    check = forecast_reports_insufficient_history()
    result = _result(forecast_result={"insufficient_history": False})
    assert not check(result).passed


def test_forecast_reports_insufficient_history_fails_when_the_tool_was_never_called():
    check = forecast_reports_insufficient_history()
    result = _result(forecast_result=None)
    assert not check(result).passed
