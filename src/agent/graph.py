"""The agent graph: router first, then (for routable questions) RAG
retrieval, then a tool-calling loop and a visible self-correction path.

    START -> router -> [lookup]                -> retrieve_schema -> agent <-> execute_tools -> build_chart_spec -> END
                     -> [analysis]              -> retrieve_schema -> agent <-> execute_tools -> build_chart_spec -> END
                     -> [forecast]              -> forecast_not_supported                                         -> END
                     -> [needs_clarification]   -> ask_clarification                                               -> END

- "router": classifies the question (lookup / analysis / forecast /
  needs_clarification) before any DB work happens — see src/agent/router.py
  for why each category exists and what it routes to today.
- "retrieve_schema": embeds the question, retrieves the most relevant
  schema chunks (see src/agent/rag/), and builds the system prompt from
  only those — this is what "RAG over the DB schema" means in practice.
  A visible, traced node rather than something that happens implicitly
  before the graph runs, so it shows up in LangSmith like every other step.
- "agent": the LLM calls a tool or writes a final answer. Which tools are
  even bound depends on the route — `lookup` only gets run_sql; `analysis`
  also gets run_stats (see src/tools/stats_tool.py), so it can run a real
  significance test or z-score outlier check instead of eyeballing an
  average comparison. Once `attempts` reaches SQL_MAX_RETRIES, this node
  stops binding tools at all, so the model *cannot* call one again — it is
  structurally forced to answer in plain text. That's what guarantees the
  loop terminates, rather than relying on the model to politely stop when
  asked.
- "execute_tools": dispatches each tool call by name to the matching guarded
  implementation, turns errors into a ToolMessage the model reads on its
  next turn (this is the self-correction step), and records the last
  *successful* SQL/stats result so the API layer can return them.
- "build_chart_spec": deterministically infers a chart spec from the last
  successful query's shape — not an LLM call, see src/tools/viz_tool.py for
  why this is code, not a prompt.
- "forecast_not_supported" / "ask_clarification": terminal nodes for the two
  categories the SQL pipeline shouldn't attempt at all — an honest
  "can't do that yet" and a clarifying question, respectively, instead of
  the agent guessing its way to a confident wrong answer.

Deliberately not using langgraph.prebuilt.create_react_agent: the loop is
simple enough to write by hand, and doing so means every step is something
we chose and can explain, rather than behavior inherited from a library
default.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Annotated, TypedDict

import duckdb
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from src.agent.llm_provider import get_llm
from src.agent.prompts import ANALYSIS_TOOL_GUIDANCE, build_system_prompt
from src.agent.rag.schema_index import assemble_schema_text, get_schema_index
from src.agent.router import classify_question
from src.config import settings
from src.db.connection import UnsafeQueryError
from src.tools.sql_tool import execute_run_sql, run_sql
from src.tools.stats_tool import execute_run_stats, run_stats
from src.tools.viz_tool import infer_chart_spec

FORECAST_NOT_SUPPORTED_TEXT = (
    "I can't forecast yet — this system doesn't have a forecasting tool or "
    "time-series data to project from (both are planned for a later slice). "
    "I can answer questions about the current catalog instead."
)


class AgentState(TypedDict):
    question: str
    messages: Annotated[list[BaseMessage], add_messages]
    attempts: int
    last_successful_sql: str | None
    last_successful_columns: list[str] | None
    last_successful_rows: list[list] | None
    last_stats_query: str | None
    last_stats_result: dict | None
    retrieved_chunk_ids: list[str] | None
    route: str | None
    clarifying_question: str | None
    chart_spec: dict | None


def router_node(state: AgentState) -> dict:
    decision = classify_question(state["question"])
    return {
        "route": decision.category,
        "clarifying_question": decision.clarifying_question or None,
    }


def route_after_router(state: AgentState) -> str:
    category = state["route"]
    if category in ("lookup", "analysis"):
        return "retrieve_schema"
    if category == "forecast":
        return "forecast_not_supported"
    return "ask_clarification"


def forecast_not_supported_node(state: AgentState) -> dict:
    return {"messages": [AIMessage(content=FORECAST_NOT_SUPPORTED_TEXT)]}


def ask_clarification_node(state: AgentState) -> dict:
    question = state["clarifying_question"] or "Could you clarify your question?"
    return {"messages": [AIMessage(content=question)]}


def retrieve_schema_node(state: AgentState) -> dict:
    chunks = get_schema_index().retrieve(state["question"], top_k=settings.rag_top_k)
    schema_text = assemble_schema_text(chunks)
    tool_guidance = ANALYSIS_TOOL_GUIDANCE if state["route"] == "analysis" else ""
    return {
        "messages": [
            SystemMessage(
                content=build_system_prompt(schema_text=schema_text, tool_guidance=tool_guidance)
            ),
            HumanMessage(content=state["question"]),
        ],
        "retrieved_chunk_ids": [c.id for c in chunks],
    }


def _tools_for_route(route: str | None) -> list:
    # lookup: just run_sql. analysis: also gets run_stats, so it can run a
    # real significance test or outlier check instead of hand-computing a
    # comparison via SQL — the concrete difference the router was built to
    # enable back in Slice 3.
    if route == "analysis":
        return [run_sql, run_stats]
    return [run_sql]


def agent_node(state: AgentState) -> dict:
    llm = get_llm()
    retries_left = state["attempts"] < settings.sql_max_retries
    model = llm.bind_tools(_tools_for_route(state["route"])) if retries_left else llm
    ai_message = model.invoke(state["messages"])
    return {"messages": [ai_message]}


def route_after_agent(state: AgentState) -> str:
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "execute_tools"
    return "build_chart_spec"


def execute_tools_node(state: AgentState) -> dict:
    last_ai = state["messages"][-1]
    tool_messages: list[ToolMessage] = []
    attempts = state["attempts"]
    update: dict = {}

    for call in last_ai.tool_calls:
        attempts += 1
        try:
            if call["name"] == "run_sql":
                result = execute_run_sql(call["args"].get("query", ""))
                update["last_successful_sql"] = call["args"].get("query", "")
                update["last_successful_columns"] = result["columns"]
                update["last_successful_rows"] = result["rows"]
            elif call["name"] == "run_stats":
                result = execute_run_stats(
                    call["args"].get("query", ""),
                    call["args"].get("mode", ""),
                    call["args"].get("z_threshold", 2.5),
                )
                update["last_stats_query"] = call["args"].get("query", "")
                update["last_stats_result"] = result
            else:
                raise ValueError(f"Unknown tool: {call['name']!r}")
            tool_messages.append(
                ToolMessage(content=json.dumps(result), tool_call_id=call["id"])
            )
        except (UnsafeQueryError, duckdb.Error, ValueError) as e:
            error_text = f"Error: {e}"
            if attempts >= settings.sql_max_retries:
                error_text += (
                    f"\n\nRetry limit ({settings.sql_max_retries}) reached. "
                    "You will not be able to call a tool again — give your final "
                    "answer now, explaining that the request could not be completed."
                )
            tool_messages.append(ToolMessage(content=error_text, tool_call_id=call["id"]))

    update["messages"] = tool_messages
    update["attempts"] = attempts
    return update


def build_chart_spec_node(state: AgentState) -> dict:
    spec = infer_chart_spec(state.get("last_successful_columns"), state.get("last_successful_rows"))
    return {"chart_spec": spec}


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("router", router_node)
    graph.add_node("retrieve_schema", retrieve_schema_node)
    graph.add_node("agent", agent_node)
    graph.add_node("execute_tools", execute_tools_node)
    graph.add_node("build_chart_spec", build_chart_spec_node)
    graph.add_node("forecast_not_supported", forecast_not_supported_node)
    graph.add_node("ask_clarification", ask_clarification_node)

    graph.set_entry_point("router")
    graph.add_conditional_edges(
        "router",
        route_after_router,
        {
            "retrieve_schema": "retrieve_schema",
            "forecast_not_supported": "forecast_not_supported",
            "ask_clarification": "ask_clarification",
        },
    )
    graph.add_edge("retrieve_schema", "agent")
    graph.add_conditional_edges(
        "agent",
        route_after_agent,
        {"execute_tools": "execute_tools", "build_chart_spec": "build_chart_spec"},
    )
    graph.add_edge("execute_tools", "agent")
    graph.add_edge("build_chart_spec", END)
    graph.add_edge("forecast_not_supported", END)
    graph.add_edge("ask_clarification", END)
    return graph.compile()


_compiled_graph = build_graph()


@dataclass
class AgentResult:
    answer: str
    sql: str | None
    columns: list[str] | None
    rows: list[list] | None
    stats_query: str | None
    stats_result: dict | None
    retrieved_chunk_ids: list[str] | None
    route: str | None
    chart_spec: dict | None


def run_agent(question: str) -> AgentResult:
    initial_state: AgentState = {
        "question": question,
        "messages": [],
        "attempts": 0,
        "last_successful_sql": None,
        "last_successful_columns": None,
        "last_successful_rows": None,
        "last_stats_query": None,
        "last_stats_result": None,
        "retrieved_chunk_ids": None,
        "route": None,
        "clarifying_question": None,
        "chart_spec": None,
    }
    final_state = _compiled_graph.invoke(initial_state, config={"run_name": "ask"})
    final_message = final_state["messages"][-1]
    answer = (
        final_message.content
        if isinstance(final_message.content, str)
        else str(final_message.content)
    )
    return AgentResult(
        answer=answer,
        sql=final_state.get("last_successful_sql"),
        columns=final_state.get("last_successful_columns"),
        rows=final_state.get("last_successful_rows"),
        stats_query=final_state.get("last_stats_query"),
        stats_result=final_state.get("last_stats_result"),
        retrieved_chunk_ids=final_state.get("retrieved_chunk_ids"),
        route=final_state.get("route"),
        chart_spec=final_state.get("chart_spec"),
    )
