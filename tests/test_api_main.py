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
from src.api import main
from src.config import settings


@pytest.fixture(autouse=True)
def _disable_cache(monkeypatch):
    # Cache behavior itself is covered by test_cache.py; disabling it here
    # keeps these tests focused on this layer and independent of the real
    # embedder / any state left over from a previous test.
    monkeypatch.setattr(settings, "semantic_cache_enabled", False)


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


def test_health_reports_db_exists_false_when_it_is_missing(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "duckdb_path", str(tmp_path / "does_not_exist.duckdb"))
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["db_exists"] is False


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
