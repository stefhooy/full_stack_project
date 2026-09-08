"""Tests for the two conditionally-included golden questions added in
Slice 58: analysis_metacritic_score_distribution (run_stats's "describe"
mode had zero end-to-end coverage before this) and
analysis_achievements_vs_review_scores (a second compare_two_groups
question, on category tags rather than genre/price).

Both are built as *optional* questions (present only when the catalog
actually supports them), not a hard assertion -- the real bug this
guards against: the games_db fixture used by every other golden-question
test has exactly 1 game tagged "Steam Achievements", one short of the 2
each group needs for a real t-test. A hard assert on that condition
would have crashed build_golden_questions() for every test in this
suite that happens to call it, not just skipped this one question --
confirmed live the first time this code was written (see DOCEXP.md's
Slice 58 entry). test_achievements_question_absent_with_the_fixtures_own_
single_achievement_game below is a direct regression test for exactly
that incident.
"""

from __future__ import annotations

import duckdb
import pytest

from src.agent.graph import AgentResult
from src.config import settings
from src.evals.golden_questions import build_golden_questions


@pytest.fixture(autouse=True)
def _use_games_db(games_db, monkeypatch):
    monkeypatch.setattr(settings, "duckdb_path", games_db)
    return games_db


def _fake_result(**overrides) -> AgentResult:
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
        route="analysis",
        chart_spec=None,
        attempts=1,
        tool_errors=0,
        total_tokens=100,
        estimated_cost_usd=0.0,
    )
    defaults.update(overrides)
    return AgentResult(**defaults)


def _find(questions, question_id):
    return next((q for q in questions if q.id == question_id), None)


# --- analysis_metacritic_score_distribution --------------------------------


def test_metacritic_question_present_with_the_fixtures_own_two_real_scores(games_db):
    # The games_db fixture already has exactly 2 real metacritic_score
    # values (85 and 90) baked in -- enough to support this question
    # without any synthetic data.
    q = _find(build_golden_questions(), "analysis_metacritic_score_distribution")
    assert q is not None
    assert q.expected_route == "analysis"
    # mean([85, 90]) == 87.5 -- a real, hand-checkable number, not just
    # "some number appears somewhere."
    assert "87.5" in q.reference_facts

    result = _fake_result(
        answer="The average Metacritic score is about 87.5.",
        stats_result={"mode": "describe", "mean": 87.5},
    )
    assert q.check(result).passed


def test_metacritic_question_absent_when_fewer_than_two_real_scores_exist(games_db):
    conn = duckdb.connect(games_db)
    conn.execute("UPDATE games SET metacritic_score = NULL WHERE appid = 3")
    conn.close()

    # Only 1 real metacritic_score left (appid 1's 85) -- not enough to
    # compute a sample standard deviation from. The question should be
    # silently absent, not a crash.
    questions = build_golden_questions()
    assert _find(questions, "analysis_metacritic_score_distribution") is None


# --- analysis_achievements_vs_review_scores --------------------------------


def test_achievements_question_absent_with_the_fixtures_own_single_achievement_game(games_db):
    # Regression test for the real incident this slice's own construction
    # hit: the fixture has exactly 1 game tagged "Steam Achievements"
    # (appid 1), one short of the 2 a real t-test needs. This must not
    # crash build_golden_questions() -- every other golden-question test
    # in this suite depends on that.
    questions = build_golden_questions()
    assert _find(questions, "analysis_achievements_vs_review_scores") is None


def _insert_achievement_games(
    games_db, *, with_achievements: list[float], without_achievements: list[float]
) -> None:
    conn = duckdb.connect(games_db)
    rows = [
        (2000 + i, f"Achiever {i}", "Single-player,Steam Achievements", score)
        for i, score in enumerate(with_achievements)
    ] + [
        (3000 + i, f"No Achievements {i}", "Single-player", score)
        for i, score in enumerate(without_achievements)
    ]
    conn.executemany(
        "INSERT INTO games (appid, name, categories, review_score) VALUES (?, ?, ?, ?)",
        rows,
    )
    conn.close()


def test_achievements_question_present_and_significant_with_a_real_gap(games_db):
    # Large n, tight clusters, and a real gap between them -- a
    # statistically robust real difference, not a coin flip.
    _insert_achievement_games(
        games_db,
        with_achievements=[0.85 + (i % 5) * 0.01 for i in range(20)],
        without_achievements=[0.55 + (i % 5) * 0.01 for i in range(20)],
    )

    q = _find(build_golden_questions(), "analysis_achievements_vs_review_scores")
    assert q is not None
    assert q.expected_route == "analysis"
    assert "statistically significant" in q.reference_facts

    result = _fake_result(
        answer="Yes, games with achievements have significantly higher review scores."
    )
    assert q.check(result).passed


def test_achievements_question_present_but_not_significant_with_no_real_gap(games_db):
    # Same size sample, but the two groups' scores are drawn from
    # essentially the same distribution -- nothing should clear p<0.05.
    _insert_achievement_games(
        games_db,
        with_achievements=[0.70 + (i % 5) * 0.01 for i in range(20)],
        without_achievements=[0.70 + (i % 5) * 0.01 for i in range(20)],
    )

    q = _find(build_golden_questions(), "analysis_achievements_vs_review_scores")
    assert q is not None
    assert "should NOT claim a significant difference" in q.reference_facts

    # The whole point of computing this live rather than assuming
    # significance: a correct "no real difference" answer must pass, not
    # be forced to claim significance the way a hardcoded assumption
    # would.
    honest_result = _fake_result(
        answer="No, there's no significant difference in review scores between the two groups."
    )
    assert q.check(honest_result).passed
