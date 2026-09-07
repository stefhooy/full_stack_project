"""Tests for build_golden_questions()'s price-outlier question
(DOCEXP.md's Slice 54 entry): it used to assume the single highest-priced
game is always a real z-score outlier, but on a smaller/differently-
shaped catalog the top price sometimes doesn't clear the threshold at
all -- a model correctly saying so was being marked wrong for being
right. Now computes the real z-score (the same formula run_stats's own
outliers mode uses) and adapts the check accordingly. Uses the real
games_db fixture (a real DuckDB file), with the fixture's own rows
normalized to a tight cluster first (so they don't quietly interfere)
plus extra rows inserted to get a large enough, realistic sample -- a
tiny n=4 sample turned out to be too small for even an extreme price to
reliably clear z_threshold=2.5, a real illustration of exactly the
small-sample fragility this fix exists to handle correctly.
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


def _normalize_fixture_prices(conn: duckdb.DuckDBPyConnection) -> None:
    # The games_db fixture's 4 rows span $0-$29.99 -- fine for other
    # golden questions, but it quietly interferes with a test that wants
    # precise control over the whole dataset's price distribution. Reset
    # them into the same cluster the synthetic rows use below, except the
    # one genuinely free-to-play row (appid 4), which a different golden
    # question's own reference facts depend on staying free.
    conn.execute("UPDATE games SET price_usd = 10.0 WHERE appid IN (1, 2, 3)")


def _insert_games(games_db, prices: dict[int, float]) -> None:
    # Minimal rows -- only appid (primary key), name, and price_usd are
    # needed for this question's own reference-fact computation; every
    # other column has no NOT NULL constraint.
    conn = duckdb.connect(games_db)
    _normalize_fixture_prices(conn)
    conn.executemany(
        "INSERT INTO games (appid, name, price_usd) VALUES (?, ?, ?)",
        [(appid, f"Synthetic Game {appid}", price) for appid, price in prices.items()],
    )
    conn.close()


def _price_outlier_question(games_db):
    return next(q for q in build_golden_questions() if q.id == "analysis_price_outliers")


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
    # 20 tightly-clustered normal games (appids 1000-1019, $8-$12) plus
    # one genuine, extreme outlier -- a large enough, realistic sample
    # that a $999.99 price actually clears z_threshold=2.5 robustly,
    # unlike the fixture's own tiny n=4.
    prices = {1000 + i: 8.0 + (i % 5) for i in range(20)}
    prices[2000] = 999.99
    _insert_games(games_db, prices)

    q = _price_outlier_question(games_db)
    assert "SHOULD flag it by name" in q.reference_facts
    assert "Synthetic Game 2000" in q.reference_facts

    flagging_it_result = _fake_result(answer="Yes, Synthetic Game 2000 is a clear outlier.")
    assert q.check(flagging_it_result).passed


def test_no_real_outlier_does_not_demand_a_specific_name(games_db):
    # Same size sample, but the "highest" price is only mildly above the
    # rest -- nothing should clear z_threshold=2.5.
    prices = {1000 + i: 8.0 + (i % 5) for i in range(20)}
    prices[2000] = 15.0
    _insert_games(games_db, prices)

    q = _price_outlier_question(games_db)
    assert "should honestly report" in q.reference_facts

    # The whole point of this fix: a correct "no outlier" answer must
    # pass, not be forced to name a specific game the way the old,
    # unconditional check did.
    honest_no_outlier_result = _fake_result(
        answer="No games have an unusually high price compared to the rest.",
        stats_result={"mode": "outliers", "outliers": []},
    )
    assert q.check(honest_no_outlier_result).passed
