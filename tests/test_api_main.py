"""Unit tests for the FastAPI surface (src/api/main.py) -- the actual path
every real request goes through, previously at 0% direct coverage despite
being the single most-exercised piece of code in the whole system. Mocks
run_agent/stream_agent (no real LLM calls; that's what tests/test_graph_*
and the `live`-marked eval suite are for) and disables the semantic cache
per-test (its own real behavior is covered by test_cache.py) so these
tests are fast and isolated to what this layer itself is responsible for:
routing, DB-existence checks, response shaping, and error handling.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src.agent.graph import AgentResult
from src.api import main, rate_limit
from src.config import settings


@pytest.fixture(autouse=True)
def _disable_cache(monkeypatch):
    # Cache behavior itself is covered by test_cache.py; disabling it here
    # keeps these tests focused on this layer and independent of the real
    # embedder / any state left over from a previous test.
    monkeypatch.setattr(settings, "semantic_cache_enabled", False)


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    # rate_limit._limiter (src/api/rate_limit.py) is a real, module-level
    # singleton shared across every test in this process -- its own
    # behavior is covered by test_rate_limit.py. Without this, enough
    # /ask and /ask/stream calls accumulating across this file's tests (a
    # real count this project just crossed for the first time when
    # Slice 48 added 4 more) eventually trips the real 10-requests/60s
    # limit partway through a run, failing later tests with a genuine 429
    # that has nothing to do with what they're actually testing.
    rate_limit._limiter._hits.clear()


@pytest.fixture()
def client():
    return TestClient(main.app)


def _fake_result(**overrides) -> AgentResult:
    defaults = dict(
        answer="Counter-Strike: Global Offensive has the highest peak concurrent players.",
        sql="SELECT name FROM games ORDER BY peak_ccu DESC LIMIT 1",
        columns=["name"],
        rows=[["Counter-Strike: Global Offensive"]],
        stats_query=None,
        stats_result=None,
        forecast_query=None,
        forecast_result=None,
        retrieved_chunk_ids=["table:games"],
        route="lookup",
        chart_spec=None,
        attempts=1,
        tool_errors=0,
        total_tokens=500,
        estimated_cost_usd=0.0001,
    )
    defaults.update(overrides)
    return AgentResult(**defaults)


# --- /health -------------------------------------------------------------


def test_health_reports_the_real_shape(client, monkeypatch, games_db):
    monkeypatch.setattr(settings, "duckdb_path", games_db)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["db_exists"] is True
    assert "self_correction" in body
    assert "usage" in body
    assert "deploy_commit" in body


def test_health_reports_db_exists_false_when_it_is_missing(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "duckdb_path", str(tmp_path / "does_not_exist.duckdb"))
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["db_exists"] is False


def test_health_reports_deploy_commit_from_render_env_var(client, monkeypatch, games_db):
    monkeypatch.setattr(settings, "duckdb_path", games_db)
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abc1234")
    resp = client.get("/health")
    assert resp.json()["deploy_commit"] == "abc1234"


def test_health_reports_deploy_commit_as_none_outside_render(client, monkeypatch, games_db):
    monkeypatch.setattr(settings, "duckdb_path", games_db)
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    resp = client.get("/health")
    assert resp.json()["deploy_commit"] is None


# --- DB-missing 503s, shared behavior across every DB-backed route ------


@pytest.mark.parametrize("path", ["/genres", "/catalog", "/ask"])
def test_db_backed_routes_503_cleanly_when_the_db_is_missing(client, monkeypatch, tmp_path, path):
    monkeypatch.setattr(settings, "duckdb_path", str(tmp_path / "does_not_exist.duckdb"))
    if path == "/ask":
        resp = client.post(path, json={"question": "anything"})
    else:
        resp = client.get(path)
    assert resp.status_code == 503


def test_games_503s_when_the_db_is_missing(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "duckdb_path", str(tmp_path / "does_not_exist.duckdb"))
    resp = client.get("/games", params={"genre": "Action"})
    assert resp.status_code == 503


# --- /ask ------------------------------------------------------------


def test_ask_returns_the_real_agent_result_shape(client, monkeypatch, games_db):
    monkeypatch.setattr(settings, "duckdb_path", games_db)
    monkeypatch.setattr(main, "run_agent", lambda question: _fake_result())
    resp = client.post("/ask", json={"question": "Which game has the highest peak CCU?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"].startswith("Counter-Strike")
    assert body["route"] == "lookup"
    assert body["cached"] is False
    assert body["attempts"] == 1
    assert body["tool_errors"] == 0
    assert body["retrieved_schema_chunks"] == ["table:games"]


def test_ask_rejects_an_empty_question_before_touching_the_agent(client, monkeypatch, games_db):
    monkeypatch.setattr(settings, "duckdb_path", games_db)
    called = False

    def _should_not_be_called(question):
        nonlocal called
        called = True
        return _fake_result()

    monkeypatch.setattr(main, "run_agent", _should_not_be_called)
    resp = client.post("/ask", json={"question": ""})
    assert resp.status_code == 422  # AskRequest's min_length=1
    assert not called


def test_ask_returns_a_friendly_503_when_the_agent_raises_and_debug_is_off(
    client, monkeypatch, games_db
):
    monkeypatch.setattr(settings, "duckdb_path", games_db)
    monkeypatch.setattr(settings, "debug", False)

    def _boom(question):
        raise RuntimeError("some real internal failure detail")

    monkeypatch.setattr(main, "run_agent", _boom)
    resp = client.post("/ask", json={"question": "anything"})
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert detail == main.FRIENDLY_ERROR_MESSAGE
    assert "some real internal failure detail" not in detail


def test_ask_returns_the_real_error_when_debug_is_on(client, monkeypatch, games_db):
    monkeypatch.setattr(settings, "duckdb_path", games_db)
    monkeypatch.setattr(settings, "debug", True)

    def _boom(question):
        raise RuntimeError("some real internal failure detail")

    monkeypatch.setattr(main, "run_agent", _boom)
    resp = client.post("/ask", json={"question": "anything"})
    assert resp.status_code == 503
    assert "some real internal failure detail" in resp.json()["detail"]


def test_ask_records_self_correction_stats_only_for_real_non_cached_runs(
    client, monkeypatch, games_db
):
    monkeypatch.setattr(settings, "duckdb_path", games_db)
    monkeypatch.setattr(main, "run_agent", lambda question: _fake_result(tool_errors=1))
    stats_before = main._run_stats.as_dict()["total_runs"]
    client.post("/ask", json={"question": "anything"})
    stats_after = main._run_stats.as_dict()["total_runs"]
    assert stats_after == stats_before + 1


# --- daily token budget (Slice 48) --------------------------------------


def test_ask_returns_a_friendly_503_when_the_daily_budget_is_exceeded(
    client, monkeypatch, games_db
):
    monkeypatch.setattr(settings, "duckdb_path", games_db)
    monkeypatch.setattr(main._run_stats, "total_tokens", settings.daily_token_budget)
    called = False

    def _should_not_be_called(question):
        nonlocal called
        called = True
        return _fake_result()

    monkeypatch.setattr(main, "run_agent", _should_not_be_called)
    resp = client.post("/ask", json={"question": "anything"})
    assert resp.status_code == 503
    assert resp.json()["detail"] == main.DAILY_BUDGET_MESSAGE
    assert not called  # never spend more once the budget is already hit


def test_ask_daily_budget_message_is_returned_even_with_debug_on(client, monkeypatch, games_db):
    # DailyBudgetExceeded is deliberately a distinct exception type from a
    # real agent failure -- this is the regression test for exactly that:
    # without it, ask()'s generic `except Exception` would swallow this
    # message the same way it swallows a real error's detail in debug=False,
    # or (in debug=True, tested here) replace it with a confusing
    # str(DailyBudgetExceeded()) instead of the real, honest message.
    monkeypatch.setattr(settings, "duckdb_path", games_db)
    monkeypatch.setattr(settings, "debug", True)
    monkeypatch.setattr(main._run_stats, "total_tokens", settings.daily_token_budget)
    resp = client.post("/ask", json={"question": "anything"})
    assert resp.status_code == 503
    assert resp.json()["detail"] == main.DAILY_BUDGET_MESSAGE


def test_ask_still_serves_a_cache_hit_when_over_the_daily_budget(client, monkeypatch, games_db):
    # A cache hit costs nothing, so it should keep working even once the
    # shared budget is exhausted for the day -- the whole point of
    # checking budget only after a confirmed cache miss.
    monkeypatch.setattr(settings, "duckdb_path", games_db)
    monkeypatch.setattr(settings, "semantic_cache_enabled", True)  # override the autouse fixture
    monkeypatch.setattr(main._run_stats, "total_tokens", settings.daily_token_budget)
    main._cache.put("What is the most popular game?", _fake_result())

    def _should_not_be_called(question):
        raise AssertionError("run_agent should not be called for a cache hit")

    monkeypatch.setattr(main, "run_agent", _should_not_be_called)
    resp = client.post("/ask", json={"question": "What is the most popular game?"})
    assert resp.status_code == 200
    assert resp.json()["cached"] is True


# --- /ask/stream -------------------------------------------------------


def test_ask_stream_emits_progress_then_a_final_event(client, monkeypatch, games_db):
    monkeypatch.setattr(settings, "duckdb_path", games_db)

    async def _fake_stream_agent(question):
        yield {"type": "progress", "node": "router", "message": "Classifying..."}
        yield {"type": "progress", "node": "retrieve_schema", "message": "Retrieving schema..."}
        yield {"type": "final", "result": _fake_result()}

    monkeypatch.setattr(main, "stream_agent", _fake_stream_agent)
    resp = client.post("/ask/stream", json={"question": "Which game has the highest peak CCU?"})
    assert resp.status_code == 200

    events = [
        json.loads(line[len("data: ") :])
        for line in resp.text.splitlines()
        if line.startswith("data: ")
    ]
    types = [e["type"] for e in events]
    assert types == ["progress", "progress", "final"]
    assert events[-1]["result"]["answer"].startswith("Counter-Strike")


def test_ask_stream_reports_a_friendly_error_event_when_the_agent_raises(
    client, monkeypatch, games_db
):
    monkeypatch.setattr(settings, "duckdb_path", games_db)

    async def _fake_stream_agent(question):
        raise RuntimeError("boom")
        yield  # pragma: no cover -- makes this a generator function; never reached

    monkeypatch.setattr(main, "stream_agent", _fake_stream_agent)
    resp = client.post("/ask/stream", json={"question": "anything"})
    assert resp.status_code == 200  # the error is inside the SSE stream, not the HTTP status
    events = [
        json.loads(line[len("data: ") :])
        for line in resp.text.splitlines()
        if line.startswith("data: ")
    ]
    assert events[-1]["type"] == "error"
    assert events[-1]["message"] == main.FRIENDLY_ERROR_MESSAGE


def test_ask_stream_reports_the_daily_budget_message_when_over_budget(
    client, monkeypatch, games_db
):
    monkeypatch.setattr(settings, "duckdb_path", games_db)
    monkeypatch.setattr(main._run_stats, "total_tokens", settings.daily_token_budget)

    async def _should_not_be_called(question):
        raise AssertionError("stream_agent should not be called once over budget")
        yield  # pragma: no cover -- makes this a generator function; never reached

    monkeypatch.setattr(main, "stream_agent", _should_not_be_called)
    resp = client.post("/ask/stream", json={"question": "anything"})
    assert resp.status_code == 200  # same convention as the error-event case above
    events = [
        json.loads(line[len("data: ") :])
        for line in resp.text.splitlines()
        if line.startswith("data: ")
    ]
    assert events[-1]["type"] == "error"
    assert events[-1]["message"] == main.DAILY_BUDGET_MESSAGE
