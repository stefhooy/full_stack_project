"""Tests for build_golden_questions()'s CCU-outlier question (DOCEXP.md's
Slice 57 entry): the identical "assumes the single highest value is
automatically a real outlier" bug already fixed once for
analysis_price_outliers (Slice 54), found a second time in
analysis_ccu_outliers during the same audit pass. Both questions now
share one helper, _outlier_check_and_reference() -- this file exercises
that helper through the CCU question specifically, mirroring
test_golden_questions_price_outlier.py's structure and its "the fixture's
own n=4 sample is too small to trust" lesson.
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


def _normalize_fixture_ccu(conn: duckdb.DuckDBPyConnection) -> None:
    # The games_db fixture's 4 rows span peak_ccu 20-9000 -- fine for other
    # golden questions, but it quietly interferes with a test that wants
    # precise control over the whole dataset's peak_ccu distribution.
    conn.execute("UPDATE games SET peak_ccu = 100 WHERE appid IN (1, 2, 3, 4)")


def _insert_games(games_db, ccu_values: dict[int, int]) -> None:
    conn = duckdb.connect(games_db)
    _normalize_fixture_ccu(conn)
    conn.executemany(
        "INSERT INTO games (appid, name, peak_ccu) VALUES (?, ?, ?)",
        [(appid, f"Synthetic Game {appid}", ccu) for appid, ccu in ccu_values.items()],
    )
    conn.close()


def _ccu_outlier_question(games_db):
    return next(q for q in build_golden_questions() if q.id == "analysis_ccu_outliers")


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


def test_a_real_statistical_outlier_is_expected_to_be_named(games_db):
    # 20 tightly-clustered normal games plus one genuine, extreme outlier
    # -- a large enough, realistic sample that a huge peak_ccu actually
    # clears z_threshold=2.5 robustly, unlike the fixture's own tiny n=4.
    ccu_values = {1000 + i: 100 + (i % 5) * 10 for i in range(20)}
    ccu_values[2000] = 5_000_000
    _insert_games(games_db, ccu_values)

    q = _ccu_outlier_question(games_db)
    assert "SHOULD flag it by name" in q.reference_facts
    assert "Synthetic Game 2000" in q.reference_facts

    flagging_it_result = _fake_result(answer="Yes, Synthetic Game 2000 is a clear outlier.")
    assert q.check(flagging_it_result).passed


def test_no_real_outlier_does_not_demand_a_specific_name(games_db):
    # Same size sample, but the "highest" peak_ccu is only mildly above
    # the rest -- nothing should clear z_threshold=2.5.
    ccu_values = {1000 + i: 100 + (i % 5) * 10 for i in range(20)}
    ccu_values[2000] = 150
    _insert_games(games_db, ccu_values)

    q = _ccu_outlier_question(games_db)
    assert "should honestly report" in q.reference_facts

    # The whole point of this fix: a correct "no outlier" answer must
    # pass, not be forced to name a specific game the way the old,
    # unconditional check did.
    honest_no_outlier_result = _fake_result(
        answer="No games have an unusually high player count compared to the rest.",
        stats_result={"mode": "outliers", "outliers": []},
    )
    assert q.check(honest_no_outlier_result).passed
