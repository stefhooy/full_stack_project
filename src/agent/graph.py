"""The agent graph: a minimal, fully-explicit loop — RAG retrieval up front,
then a tool-calling loop with one tool (run_sql) and a visible
self-correction path.

    START -> retrieve_schema -> agent -> [has tool_calls?] -> execute_tools -> agent -> ... -> END
                                       \\-> no tool_calls -> END

- "retrieve_schema": embeds the question, retrieves the most relevant
  schema chunks (see src/agent/rag/), and builds the system prompt from
  only those — this is what "RAG over the DB schema" means in practice.
  A visible, traced node rather than something that happens implicitly
  before the graph runs, so it shows up in LangSmith like every other step.
- "agent": the LLM either calls run_sql or writes a final answer. Once
  `attempts` reaches SQL_MAX_RETRIES, this node stops binding the tool at
  all, so the model *cannot* call it again — it is structurally forced to
  answer in plain text. That's what guarantees the loop terminates, rather
  than relying on the model to politely stop when asked.
- "execute_tools": runs each tool call through the guarded DB layer, turns
  DuckDB/validation errors into a ToolMessage the model reads on its next
  turn (this is the self-correction step), and records the last
  *successful* SQL + rows so the API layer can return them.

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
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from src.agent.llm_provider import get_llm
from src.agent.prompts import build_system_prompt
from src.agent.rag.schema_index import assemble_schema_text, get_schema_index
from src.config import settings
from src.db.connection import UnsafeQueryError
from src.tools.sql_tool import execute_run_sql, run_sql


class AgentState(TypedDict):
    question: str
    messages: Annotated[list[BaseMessage], add_messages]
    attempts: int
    last_successful_sql: str | None
    last_successful_columns: list[str] | None
    last_successful_rows: list[list] | None
    retrieved_chunk_ids: list[str] | None


def retrieve_schema_node(state: AgentState) -> dict:
    chunks = get_schema_index().retrieve(state["question"], top_k=settings.rag_top_k)
    schema_text = assemble_schema_text(chunks)
    return {
        "messages": [
            SystemMessage(content=build_system_prompt(schema_text=schema_text)),
            HumanMessage(content=state["question"]),
        ],
        "retrieved_chunk_ids": [c.id for c in chunks],
    }


def agent_node(state: AgentState) -> dict:
    llm = get_llm()
    retries_left = state["attempts"] < settings.sql_max_retries
    model = llm.bind_tools([run_sql]) if retries_left else llm
    ai_message = model.invoke(state["messages"])
    return {"messages": [ai_message]}


def route_after_agent(state: AgentState) -> str:
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "execute_tools"
    return END


def execute_tools_node(state: AgentState) -> dict:
    last_ai = state["messages"][-1]
    tool_messages: list[ToolMessage] = []
    attempts = state["attempts"]
    update: dict = {}

    for call in last_ai.tool_calls:
        attempts += 1
        query = call["args"].get("query", "")
        try:
            result = execute_run_sql(query)
            tool_messages.append(
                ToolMessage(content=json.dumps(result), tool_call_id=call["id"])
            )
            update["last_successful_sql"] = query
            update["last_successful_columns"] = result["columns"]
            update["last_successful_rows"] = result["rows"]
        except (UnsafeQueryError, duckdb.Error) as e:
            error_text = f"SQL error: {e}"
            if attempts >= settings.sql_max_retries:
                error_text += (
                    f"\n\nRetry limit ({settings.sql_max_retries}) reached. "
                    "You will not be able to call run_sql again — give your final "
                    "answer now, explaining that the query could not be completed."
                )
            tool_messages.append(ToolMessage(content=error_text, tool_call_id=call["id"]))

    update["messages"] = tool_messages
    update["attempts"] = attempts
    return update


def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("retrieve_schema", retrieve_schema_node)
    graph.add_node("agent", agent_node)
    graph.add_node("execute_tools", execute_tools_node)
    graph.set_entry_point("retrieve_schema")
    graph.add_edge("retrieve_schema", "agent")
    graph.add_conditional_edges(
        "agent", route_after_agent, {"execute_tools": "execute_tools", END: END}
    )
    graph.add_edge("execute_tools", "agent")
    return graph.compile()


_compiled_graph = build_graph()


@dataclass
class AgentResult:
    answer: str
    sql: str | None
    columns: list[str] | None
    rows: list[list] | None
    retrieved_chunk_ids: list[str] | None


def run_agent(question: str) -> AgentResult:
    initial_state: AgentState = {
        "question": question,
        "messages": [],
        "attempts": 0,
        "last_successful_sql": None,
        "last_successful_columns": None,
        "last_successful_rows": None,
        "retrieved_chunk_ids": None,
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
        retrieved_chunk_ids=final_state.get("retrieved_chunk_ids"),
    )
