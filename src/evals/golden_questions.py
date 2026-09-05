"""The golden question set.

Reference facts are computed *live* from the DB via independent queries —
not hardcoded numbers — so this eval set stays correct if ingestion is
re-run with different games or updated prices/reviews. `build_golden_questions()`
is a function, not a module-level constant, specifically so it queries the
DB at eval time rather than at import time (importing this module shouldn't
require the DB to already exist).

Q3 exists specifically to catch the group-mislabeling bug found in Slice 4
(DOCEXP.md): the model previously labeled a SQL group 'free_to_play'
without actually filtering to price_usd = 0. Free-to-play games are free
*by definition* (price_usd = 0), so a correctly-labeled free-to-play group
must have a mean price of ~$0 — any other value proves the label doesn't
match the filter, regardless of whether the reported p-value looks
plausible. This is a regression test for a real, previously-observed bug,
not a hypothetical one.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

from src.agent.graph import AgentResult
from src.config import settings
from src.evals.checks import (
    Check,
    CheckResult,
    all_of,
    contains_number,
    contains_text,
    forecast_has_real_projection,
    forecast_reports_insufficient_history,
    no_data_fabricated,
    route_is,
)


@dataclass
class GoldenQuestion:
    id: str
    question: str
    expected_route: str
    check: Check
    reference_facts: str  # plain-text ground truth, given to the LLM judge


def _query_one(conn: duckdb.DuckDBPyConnection, sql: str):
    row = conn.execute(sql).fetchone()
    assert row is not None, f"reference query returned no rows: {sql!r}"
    return row[0]


def _check_action_vs_f2p_not_mislabeled(result: AgentResult) -> CheckResult:
    """Two valid paths to a correct answer, not one: run_stats's
    compare_two_groups mode (the originally-intended path), or a plain
    run_sql aggregate whose free-to-play-labeled column's *actual returned
    value* is really ~$0. Checks the real returned data, not which tool
    produced it or the SQL's own text -- a model that answers correctly via
    plain SQL has not reproduced the Slice 4 bug this check exists to
    catch, even though it skipped run_stats. Every real failure of the
    original, tool-gated version of this check (Slices 24, 27, 28) turned
    out, on actually inspecting the SQL each time, to be exactly that:
    correctly-filtered SQL, rejected only because run_stats wasn't the
    tool used -- not a real recurrence of the labeling bug. See DOCEXP.md's
    Slice 30 entry for the full correction."""
    if result.stats_result and result.stats_result.get("mode") == "compare_two_groups":
        sr = result.stats_result
        groups = [(sr["group_a"], sr["mean_a"]), (sr["group_b"], sr["mean_b"])]
        f2p_group = next((g for g in groups if "free" in g[0].lower()), None)
        if f2p_group is None:
            return CheckResult(
                False, f"no group labeled free-to-play among {[g[0] for g in groups]}"
            )
        label, mean = f2p_group
        if abs(mean) > 0.5:
            return CheckResult(
                False,
                f"group {label!r} claims to be free-to-play but has mean price "
                f"${mean:.2f} (should be ~$0 by definition) -- likely mislabeled: "
                f"the query probably didn't actually filter price_usd = 0",
            )
        return CheckResult(True, f"group {label!r} (via run_stats) correctly has ~$0 mean price")

    if result.columns and result.rows:
        for col_idx, col_name in enumerate(result.columns):
            if "free" not in col_name.lower() and "f2p" not in col_name.lower():
                continue
            value = result.rows[0][col_idx]
            if value is None:
                continue
            if abs(value) <= 0.5:
                return CheckResult(
                    True, f"column {col_name!r} (via plain SQL) correctly has ~$0 mean price"
                )
            return CheckResult(
                False,
                f"column {col_name!r} claims free-to-play but its actual returned value "
                f"is {value} (should be ~$0 by definition) -- likely mislabeled: the "
                f"query probably didn't actually filter price_usd = 0",
            )

    return CheckResult(
        False,
        "expected either a compare_two_groups stats_result, or a plain-SQL column "
        f"labeled free-to-play with a real returned value; got "
        f"stats_result={result.stats_result!r}, columns={result.columns!r}, sql={result.sql!r}",
    )


def build_golden_questions() -> list[GoldenQuestion]:
    conn = duckdb.connect(settings.duckdb_abs_path, read_only=True)
    try:
        top_ccu_name = _query_one(conn, "SELECT name FROM games ORDER BY peak_ccu DESC LIMIT 1")
        high_review_count = _query_one(
            conn, "SELECT COUNT(*) FROM games WHERE review_score > 0.9"
        )
        f2p_count = _query_one(conn, "SELECT COUNT(*) FROM games WHERE price_usd = 0")
        strategy_avg_price = _query_one(
            conn, "SELECT AVG(price_usd) FROM games WHERE genre LIKE '%Strategy%'"
        )
        linux_count = _query_one(
            conn, "SELECT COUNT(*) FROM games WHERE platforms LIKE '%linux%'"
        )
        price_outlier_name = _query_one(
            conn, "SELECT name FROM games ORDER BY price_usd DESC LIMIT 1"
        )
        f2p_review_mean = _query_one(
            conn, "SELECT AVG(review_score) FROM games WHERE price_usd = 0"
        )
        paid_review_mean = _query_one(
            conn, "SELECT AVG(review_score) FROM games WHERE price_usd > 0"
        )
        csgo_snapshots = _query_one(
            conn,
            "SELECT COUNT(DISTINCT pc.polled_at) FROM player_counts pc "
            "JOIN games g ON g.appid = pc.appid "
            "WHERE g.name = 'Counter-Strike: Global Offensive'",
        )
        hoi4_snapshots = _query_one(
            conn,
            "SELECT COUNT(DISTINCT pc.polled_at) FROM player_counts pc "
            "JOIN games g ON g.appid = pc.appid WHERE g.name = 'Hearts of Iron IV'",
        )
        # Whichever real, currently most-popular game the poller hasn't
        # tracked yet -- queried live, not hardcoded, so this stays correct
        # as the poller's own tracked set grows over time (see DOCEXP.md's
        # Slice 43 entry for why a fixed game name here would eventually
        # go stale).
        untracked_game = _query_one(
            conn,
            "SELECT g.name FROM games g "
            "WHERE g.appid NOT IN (SELECT DISTINCT appid FROM player_counts) "
            "ORDER BY g.peak_ccu DESC LIMIT 1",
        )
    finally:
        conn.close()

    return [
        GoldenQuestion(
            id="lookup_top_ccu",
            question="Which game has the highest peak concurrent player count?",
            expected_route="lookup",
            check=all_of(route_is("lookup"), contains_text(top_ccu_name)),
            reference_facts=f"The game with the highest peak_ccu is {top_ccu_name!r}.",
        ),
        GoldenQuestion(
            id="lookup_high_review_count",
            question="How many games have a review score above 90%?",
            expected_route="lookup",
            check=all_of(
                route_is("lookup"), contains_number(high_review_count, tolerance=0.5, rel=False)
            ),
            reference_facts=(
                f"COUNT(*) WHERE review_score > 0.9 is {high_review_count} "
                "(review_score is a 0..1 fraction, so 90% means review_score > 0.9)."
            ),
        ),
        GoldenQuestion(
            id="analysis_action_vs_f2p_not_mislabeled",
            question=(
                "Whats the average price of games tagged as Action, and how does that "
                "compare to free-to-play games?"
            ),
            expected_route="analysis",
            check=all_of(route_is("analysis"), _check_action_vs_f2p_not_mislabeled),
            reference_facts=(
                f"There are {f2p_count} free-to-play games (price_usd = 0), so any group "
                "correctly labeled 'free-to-play' must have a mean price of $0.00 exactly."
            ),
        ),
        GoldenQuestion(
            id="analysis_ccu_outliers",
            question=(
                "Are there any games with an unusually high number of concurrent players "
                "compared to the rest?"
            ),
            expected_route="analysis",
            check=all_of(route_is("analysis"), contains_text(top_ccu_name)),
            reference_facts=(
                f"{top_ccu_name!r} has by far the highest peak_ccu in the dataset and should "
                "be flagged as a clear outlier."
            ),
        ),
        GoldenQuestion(
            id="needs_clarification_ambiguous",
            question="Is this game good?",
            expected_route="needs_clarification",
            check=all_of(route_is("needs_clarification"), no_data_fabricated()),
            reference_facts=(
                "The question doesn't name a game, so the correct response is a clarifying "
                "question asking which game — not a guess."
            ),
        ),
        # Slice 43: grown from 5 to 15 questions (a 5-question set was sound
        # methodology but smoke-test statistical weight -- see DOCEXP.md).
        # The 10 below add real coverage of a data dimension not touched
        # above (platforms, genre pricing), a second, numerically robust
        # analysis comparison (the first, Action vs Strategy review scores,
        # had a borderline p=0.03 that a small re-ingestion could flip),
        # forecast (removed in Slice 27 when it had no real tool behind it,
        # restored now that Slice 40/41 confirmed it genuinely works), and
        # two more genuinely distinct needs_clarification phrasings.
        GoldenQuestion(
            id="lookup_avg_strategy_price",
            question="What is the average price of games tagged as Strategy?",
            expected_route="lookup",
            check=all_of(
                route_is("lookup"), contains_number(strategy_avg_price, tolerance=0.5, rel=False)
            ),
            reference_facts=(
                f"AVG(price_usd) WHERE genre LIKE '%Strategy%' is ${strategy_avg_price:.2f}."
            ),
        ),
        GoldenQuestion(
            id="lookup_linux_count",
            question="How many games support Linux?",
            expected_route="lookup",
            check=all_of(
                route_is("lookup"), contains_number(linux_count, tolerance=0.5, rel=False)
            ),
            reference_facts=f"COUNT(*) WHERE platforms LIKE '%linux%' is {linux_count}.",
        ),
        GoldenQuestion(
            id="analysis_f2p_vs_paid_review_scores",
            question=(
                "Is there a significant difference in review scores between free-to-play "
                "and paid games?"
            ),
            expected_route="analysis",
            check=all_of(route_is("analysis"), contains_text("significant")),
            reference_facts=(
                f"Free-to-play games (price_usd = 0) average review_score "
                f"{f2p_review_mean:.3f}; paid games average {paid_review_mean:.3f}. A real "
                "Welch's t-test on this data finds p << 0.001 -- an unambiguous, robust "
                "difference, not a borderline call."
            ),
        ),
        GoldenQuestion(
            id="analysis_price_outliers",
            question="Are there any games with an unusually high price compared to the rest?",
            expected_route="analysis",
            check=all_of(route_is("analysis"), contains_text(price_outlier_name)),
            reference_facts=(
                f"{price_outlier_name!r} has the single highest price_usd in the dataset and "
                "should be flagged as a clear outlier."
            ),
        ),
        GoldenQuestion(
            id="forecast_csgo_next_month",
            question="How many players will Counter-Strike: Global Offensive have next month?",
            expected_route="forecast",
            check=all_of(route_is("forecast"), forecast_has_real_projection()),
            reference_facts=(
                f"Counter-Strike: Global Offensive has {csgo_snapshots} real historical "
                "live-player snapshots, enough to fit a real (if not necessarily high-"
                "confidence) linear-trend projection -- the tool should NOT report "
                "insufficient_history for this game."
            ),
        ),
        GoldenQuestion(
            id="forecast_hoi4_next_week",
            question="How many players will Hearts of Iron IV have next week?",
            expected_route="forecast",
            check=all_of(route_is("forecast"), forecast_has_real_projection()),
            reference_facts=(
                f"Hearts of Iron IV has {hoi4_snapshots} real historical live-player "
                "snapshots, enough for a real projection over this short (7-day) horizon -- "
                "the tool should NOT report insufficient_history for this game."
            ),
        ),
        GoldenQuestion(
            id="forecast_insufficient_history_is_honest",
            question=f"How many players will {untracked_game} have next month?",
            expected_route="forecast",
            check=all_of(route_is("forecast"), forecast_reports_insufficient_history()),
            reference_facts=(
                f"{untracked_game!r} has zero real historical live-player snapshots (it "
                "isn't in the set of games the live-player poller currently tracks). The "
                "only honest answer is that there isn't enough history to forecast from -- "
                "any specific projected number would be fabricated."
            ),
        ),
        GoldenQuestion(
            id="needs_clarification_best_game",
            question="What's the best game?",
            expected_route="needs_clarification",
            check=all_of(route_is("needs_clarification"), no_data_fabricated()),
            reference_facts=(
                "\"Best\" by what criterion (reviews, players, price) is undefined, and no "
                "game or genre is named -- the correct response asks what the user actually "
                "means, not a guess at a single \"best\" game."
            ),
        ),
        GoldenQuestion(
            id="needs_clarification_compare_prices",
            question="Compare the prices of these games.",
            expected_route="needs_clarification",
            check=all_of(route_is("needs_clarification"), no_data_fabricated()),
            reference_facts=(
                "\"These games\" doesn't name any games at all -- the correct response asks "
                "which games to compare, not a guess at which ones \"these\" refers to."
            ),
        ),
        GoldenQuestion(
            id="needs_clarification_should_i_buy",
            question="Should I buy it?",
            expected_route="needs_clarification",
            check=all_of(route_is("needs_clarification"), no_data_fabricated()),
            reference_facts=(
                "\"It\" doesn't name a game, and \"should I buy\" isn't a fact this dataset "
                "can answer even once a game is named -- the correct response asks which "
                "game, not a guess."
            ),
        ),
    ]
