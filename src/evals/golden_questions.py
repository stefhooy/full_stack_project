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
import numpy as np
from scipy import stats as scipy_stats

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
    stats_result_has_mode,
)
from src.tools.forecast_tool import execute_run_forecast


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


def _outlier_check_and_reference(
    conn: duckdb.DuckDBPyConnection, column: str, noun: str
) -> tuple[Check, str]:
    """Whether the single highest `column` value in the dataset is a real
    z-score outlier, computed with the exact same formula run_stats's own
    outliers mode uses (src/tools/stats_tool.py: sample stddev,
    z_threshold=2.5) -- not assumed. Shared by analysis_price_outliers
    and analysis_ccu_outliers, both of which used to just assume "the
    single highest X" is automatically a clear outlier -- a real,
    confirmed bug (DOCEXP.md's Slice 54 entry, found a second time in
    Slice 56's own audit for exactly this pattern): on a smaller/
    differently-shaped catalog, the top value sometimes doesn't clear
    the threshold at all, and a model correctly saying so was being
    marked wrong for being right. `column` is always one of this
    module's own hardcoded call sites, never user input -- the f-string
    below is safe for that reason, not because the value is escaped."""
    row = conn.execute(
        f"SELECT name, "
        f"({column} - (SELECT AVG({column}) FROM games)) "
        f"/ (SELECT STDDEV_SAMP({column}) FROM games) AS z_score "
        f"FROM games ORDER BY {column} DESC LIMIT 1"
    ).fetchone()
    assert row is not None, "games table appears to be empty"
    name, z_score = row
    if abs(z_score) > 2.5:
        check = all_of(route_is("analysis"), contains_text(name))
        reference_facts = (
            f"{name!r} has the single highest {noun} in the dataset, a real z-score of "
            f"{z_score:.2f} against the standard z_threshold=2.5 run_stats itself uses -- "
            "a rigorous outlier check SHOULD flag it by name."
        )
        return check, reference_facts

    # Route-only: no single fact to assert positively here (the correct
    # answer is "no strong outlier," which has no one name to check for),
    # and inventing a check for what the answer must NOT say is exactly
    # the kind of fragile, enumerate-every-wrong-answer check this
    # project avoids elsewhere. The LLM judge, given the accurate
    # reference facts below, already assesses this correctly (confirmed
    # directly for the price case, DOCEXP.md's Slice 54 entry).
    check = route_is("analysis")
    reference_facts = (
        f"{name!r} has the single highest {noun} in the dataset, but its real z-score is "
        f"only {z_score:.2f} -- below the standard z_threshold=2.5 run_stats itself uses. "
        "A rigorous outlier check should honestly report that nothing clears the threshold, "
        f"not force this game forward as a clear outlier just because it's the single "
        f"highest {noun}."
    )
    return check, reference_facts


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
        # Whether the single highest-priced game is actually a real
        # statistical outlier, computed with the exact same formula
        # run_stats's own outliers mode uses -- not assumed. See
        # _outlier_check_and_reference's docstring for the real, confirmed
        # bug this closes (DOCEXP.md's Slice 54 and Slice 57 entries).
        price_outlier_check, price_outlier_reference_facts = _outlier_check_and_reference(
            conn, "price_usd", "price_usd"
        )
        ccu_outlier_check, ccu_outlier_reference_facts = _outlier_check_and_reference(
            conn, "peak_ccu", "peak_ccu"
        )
        # Slice 58 follow-up: a third outlier question, on a metric neither
        # of the above two touches, added specifically to give the
        # "analysis" route more independent samples -- one flaky
        # classification (the real one that failed Slice 58's own CI run)
        # swings a smaller fraction of the aggregate score when there are
        # more analysis-route questions to average over.
        discount_outlier_check, discount_outlier_reference_facts = _outlier_check_and_reference(
            conn, "discount_pct", "discount_pct"
        )
        # run_stats's third mode, "describe", had zero end-to-end golden-
        # question coverage until this slice -- a real, previously-unnoticed
        # gap (compare_two_groups and outliers both had coverage above).
        # metacritic_score is a good column for it: genuinely numeric, a
        # real spread (0-100), and NULL for un-scored games (matching this
        # column's own real quirk, see schema_corpus.py) -- so this also
        # exercises _describe()'s NULL-filtering for real, not just its
        # arithmetic. Computed with DuckDB's own aggregates rather than
        # pulling raw rows into Python, but the same formulas _describe()
        # itself uses: STDDEV_SAMP (sample stddev, matches numpy's ddof=1),
        # MEDIAN, PERCENTILE_CONT (linear interpolation, matches numpy's
        # default np.percentile behavior).
        # Also optional, not a hard assertion, for the same reason as
        # achievements_question below: "at least 2 games with a real
        # metacritic_score" is a real assumption about catalog shape, not
        # a global precondition every other query already relies on (like
        # the games table being non-empty), so a small or oddly-sampled
        # catalog can legitimately not support this question without that
        # meaning anything is broken.
        # p25/p75 included here specifically because _describe() itself
        # always computes and returns them as part of stats_result -- a
        # real judge run flagged a model reporting them as "unsupported"
        # (DOCEXP.md's Slice 58 entry) purely because reference_facts
        # didn't happen to restate every field the tool actually returns.
        # That's a real gap in this reference text, not a model
        # hallucination: the fix is completeness here, not a smaller
        # answer from the model.
        metacritic_stats_row = conn.execute(
            "SELECT COUNT(*), AVG(metacritic_score), MEDIAN(metacritic_score), "
            "STDDEV_SAMP(metacritic_score), MIN(metacritic_score), MAX(metacritic_score), "
            "PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY metacritic_score), "
            "PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY metacritic_score) "
            "FROM games WHERE metacritic_score IS NOT NULL"
        ).fetchone()
        assert metacritic_stats_row is not None, "games table appears to be empty"
        (
            metacritic_n,
            metacritic_mean,
            metacritic_median,
            metacritic_stddev,
            metacritic_min,
            metacritic_max,
            metacritic_p25,
            metacritic_p75,
        ) = metacritic_stats_row
        metacritic_question: GoldenQuestion | None = None
        if metacritic_n is not None and metacritic_n > 1:
            metacritic_reference_facts = (
                f"Across the {metacritic_n} games with a real Metacritic score (NULL scores "
                "excluded, since NULL here means 'never scored,' not 'scored zero'), the mean "
                f"is {metacritic_mean:.1f}, median {metacritic_median:.1f}, and sample "
                f"standard deviation {metacritic_stddev:.1f}, ranging from "
                f"{metacritic_min:.0f} to {metacritic_max:.0f} (25th percentile "
                f"{metacritic_p25:.1f}, 75th percentile {metacritic_p75:.1f} -- the tool "
                "itself always computes these too, so reporting them is correct, not "
                "an unsupported addition)."
            )
            metacritic_question = GoldenQuestion(
                id="analysis_metacritic_score_distribution",
                question=(
                    "What's the average and spread of Metacritic scores across the games "
                    "that have one?"
                ),
                expected_route="analysis",
                check=all_of(
                    route_is("analysis"),
                    stats_result_has_mode("describe"),
                    contains_number(metacritic_mean),
                ),
                reference_facts=metacritic_reference_facts,
            )
        # A second compare_two_groups question on a dimension neither
        # existing one touches (genre, price) -- category tags. Computes
        # the real Welch's t-test live (the exact formula run_stats's own
        # compare_two_groups mode uses) rather than assuming significance,
        # the same "don't assume, compute" principle as the outlier
        # questions above -- analysis_f2p_vs_paid_review_scores predates
        # that principle and still hand-asserts "p << 0.001" without a
        # live check; not touched here to keep this slice's diff focused,
        # but the same fragility technically applies to it too.
        #
        # Built as an optional question, not a hard assertion -- unlike the
        # games table itself (which every other reference query already
        # assumes is non-empty), "at least 2 games in each achievement
        # group" is a real assumption about catalog *shape* that a small
        # or oddly-sampled catalog (this project's own test fixtures
        # included) can genuinely violate. build_golden_questions() is
        # called by plenty of tests that have nothing to do with this
        # question, so a hard assert here would break all of them, not
        # just skip this one question -- same reasoning as
        # tracked_forecastable_games below producing 0, 1, or 2 questions
        # rather than assuming exactly 2 tracked games always exist.
        achievements_rows = conn.execute(
            "SELECT CASE WHEN categories LIKE '%Steam Achievements%' THEN 'has_achievements' "
            "ELSE 'no_achievements' END AS group_label, review_score "
            "FROM games WHERE review_score IS NOT NULL"
        ).fetchall()
        achievements_groups: dict[str, list[float]] = {}
        for achievements_label, achievements_value in achievements_rows:
            achievements_groups.setdefault(achievements_label, []).append(
                float(achievements_value)
            )
        has_achievements_values = np.array(achievements_groups.get("has_achievements", []))
        no_achievements_values = np.array(achievements_groups.get("no_achievements", []))
        achievements_question: GoldenQuestion | None = None
        if has_achievements_values.size >= 2 and no_achievements_values.size >= 2:
            _, achievements_p_value = scipy_stats.ttest_ind(
                has_achievements_values, no_achievements_values, equal_var=False
            )
            achievements_mean_with = float(has_achievements_values.mean())
            achievements_mean_without = float(no_achievements_values.mean())
            if achievements_p_value < 0.05:
                achievements_check = all_of(route_is("analysis"), contains_text("significant"))
                achievements_reference_facts = (
                    f"Games with a 'Steam Achievements' category tag average review_score "
                    f"{achievements_mean_with:.3f}; games without average "
                    f"{achievements_mean_without:.3f}. A real Welch's t-test finds "
                    f"p={achievements_p_value:.4g} -- a real, statistically significant "
                    "difference."
                )
            else:
                achievements_check = route_is("analysis")
                achievements_reference_facts = (
                    f"Games with a 'Steam Achievements' category tag average review_score "
                    f"{achievements_mean_with:.3f}; games without average "
                    f"{achievements_mean_without:.3f}. A real Welch's t-test finds "
                    f"p={achievements_p_value:.4g} -- not below the standard 0.05 "
                    "significance threshold, so a rigorous answer should NOT claim a "
                    "significant difference just because the two means differ numerically."
                )
            achievements_question = GoldenQuestion(
                id="analysis_achievements_vs_review_scores",
                question=(
                    "Do games with Steam Achievements have significantly different review "
                    "scores than games without?"
                ),
                expected_route="analysis",
                check=achievements_check,
                reference_facts=achievements_reference_facts,
            )
        f2p_review_mean = _query_one(
            conn, "SELECT AVG(review_score) FROM games WHERE price_usd = 0"
        )
        paid_review_mean = _query_one(
            conn, "SELECT AVG(review_score) FROM games WHERE price_usd > 0"
        )
        # Whichever real, currently-tracked games actually have enough
        # history to forecast from, queried live rather than hardcoded to
        # specific names -- a real, previously-confirmed bug (DOCEXP.md's
        # Slice 51/52 entries): "Counter-Strike: Global Offensive" and
        # "Hearts of Iron IV" were hardcoded here, but CI builds a small,
        # ~100-game catalog (SteamSpy's top 100 by *owners*, not by
        # peak_ccu or by which games the poller happens to track) fresh
        # each run, and a hardcoded niche game isn't guaranteed to survive
        # that cut, or even the same popular one every day. Ordered by
        # peak_ccu DESC so the two picked are the most prominent tracked
        # games available today, mirroring untracked_game's own query
        # just below (same live-query principle, opposite condition).
        tracked_forecastable_games = conn.execute(
            "SELECT g.appid, g.name, COUNT(DISTINCT pc.polled_at) AS snapshots FROM games g "
            "JOIN player_counts pc ON pc.appid = g.appid "
            "GROUP BY g.appid, g.name, g.peak_ccu "
            "HAVING COUNT(DISTINCT pc.polled_at) >= 2 "
            "ORDER BY g.peak_ccu DESC LIMIT 2"
        ).fetchall()
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

    questions: list[GoldenQuestion] = [
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
            check=ccu_outlier_check,
            reference_facts=ccu_outlier_reference_facts,
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
            check=price_outlier_check,
            reference_facts=price_outlier_reference_facts,
        ),
        GoldenQuestion(
            id="analysis_discount_outliers",
            question="Are there any games with an unusually large discount compared to the rest?",
            expected_route="analysis",
            check=discount_outlier_check,
            reference_facts=discount_outlier_reference_facts,
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

    # Only included when the catalog actually supports them (see each
    # question's own construction above for why this is conditional
    # rather than a hard assertion: build_golden_questions() is called by
    # plenty of tests that have nothing to do with either question, so a
    # hard assert on a narrow catalog-shape assumption would break all of
    # them, not just skip the one question that can't be answered today).
    if metacritic_question is not None:
        questions.append(metacritic_question)
    if achievements_question is not None:
        questions.append(achievements_question)

    # Two forecast-with-real-data questions, built from whichever tracked
    # games actually qualified above -- 0, 1, or 2 of them, never assumed
    # to be exactly 2. Real horizons (30 days, then 7) kept distinct on
    # purpose: they exercise different parts of _forecast()'s own
    # low-confidence logic (a longer horizon relative to the observed
    # span is flagged differently than a short one), not just cosmetic
    # variety.
    # Slice 58 follow-up: the real projected_value used to be deliberately
    # left out of reference_facts (it's data-dependent, computed live) --
    # but that meant a judge run had nothing to check the model's own
    # reported number against, and twice flagged a completely correct,
    # tool-grounded answer as "fabricating data" for reporting the exact
    # real projection (DOCEXP.md's Slice 58 entry). Fixed by computing the
    # real projection here too, via the identical call the agent's own
    # execute_tools_node makes -- same "call the real tool, don't guess"
    # principle as _outlier_check_and_reference() above. This is safe to
    # precompute: _forecast() is a pure function of the DB's own snapshot
    # timestamps/values and horizon_days, never wall-clock "now", and
    # nothing writes to player_counts between here and the live agent
    # call moments later in the same CI job -- so this is the actual
    # number the tool will independently (re)compute, not a guess at it.
    horizons = [("next month", 30), ("next week", 7)]
    for i, (appid, name, snapshots) in enumerate(tracked_forecastable_games):
        phrase, horizon_days = horizons[i]
        real_forecast = execute_run_forecast(
            f"SELECT polled_at, player_count FROM player_counts WHERE appid = {appid}",
            horizon_days,
        )
        questions.append(
            GoldenQuestion(
                id=f"forecast_tracked_game_{i + 1}_{phrase.replace(' ', '_')}",
                question=f"How many players will {name} have {phrase}?",
                expected_route="forecast",
                check=all_of(route_is("forecast"), forecast_has_real_projection()),
                reference_facts=(
                    f"{name!r} has {snapshots} real historical live-player snapshots, "
                    f"enough to fit a real (if not necessarily high-confidence) "
                    f"linear-trend projection over this {horizon_days}-day horizon. A real "
                    f"linear-trend fit over that history projects approximately "
                    f"{real_forecast['projected_value']:.0f} players -- the tool should "
                    "NOT report insufficient_history for this game, and a reported "
                    "number at or near this real projection is correct, not fabricated."
                ),
            )
        )

    return questions
