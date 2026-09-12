"""The agent graph: router first, then (for routable questions) RAG
retrieval, then a tool-calling loop and a visible self-correction path.

    START -> router -> [lookup, analysis, forecast]
                        -> retrieve_schema -> agent <-> execute_tools -> build_chart_spec -> END
                     -> [needs_clarification] -> ask_clarification -> END

- "router": classifies the question (lookup / analysis / forecast /
  needs_clarification) before any DB work happens, see src/agent/router.py
  for why each category exists and what it routes to today.
- "retrieve_schema": embeds the question, retrieves the most relevant
  schema chunks (see src/agent/rag/), and builds the system prompt from
  only those, this is what "RAG over the DB schema" means in practice.
  A visible, traced node rather than something that happens implicitly
  before the graph runs, so it shows up in LangSmith like every other step.
- "agent": the LLM calls a tool or writes a final answer. Which tools are
  even bound depends on the route, `lookup` only gets run_sql; `analysis`
  also gets run_stats (see src/tools/stats_tool.py), so it can run a real
  significance test or z-score outlier check instead of eyeballing an
  average comparison; `forecast` gets run_forecast (see
  src/tools/forecast_tool.py), a real linear-trend projection over
  player_counts history. Once `attempts` reaches SQL_MAX_RETRIES, this node
  stops binding tools at all, so the model *cannot* call one again, it is
  structurally forced to answer in plain text. That's what guarantees the
  loop terminates, rather than relying on the model to politely stop when
  asked.
- "execute_tools": dispatches each tool call by name to the matching guarded
  implementation, turns errors into a ToolMessage the model reads on its
  next turn (this is the self-correction step), and records the last
  *successful* SQL/stats/forecast result so the API layer can return them.
- "build_chart_spec": deterministically infers a chart spec from the last
  successful query's shape, not an LLM call, see src/tools/viz_tool.py for
  why this is code, not a prompt.
- "ask_clarification": terminal node for questions too ambiguous for the SQL
  pipeline to attempt at all, a clarifying question back, instead of the
  agent guessing its way to a confident wrong answer.

`forecast` used to be its own terminal "not supported yet" node (no
forecasting tool or time-series data existed). Both now exist (Slice 7's
player_counts, this slice's run_forecast), so forecast questions flow
through the same loop as lookup/analysis, the tool itself, not a route-
level block, is what decides honestly whether there's enough history to
answer. See forecast_tool.py's docstring.

Deliberately not using langgraph.prebuilt.create_react_agent: the loop is
simple enough to write by hand, and doing so means every step is something
we chose and can explain, rather than behavior inherited from a library
default.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Annotated, TypedDict, cast

try:
    import resource  # Unix-only (Render/Linux); absent on Windows local dev
except ImportError:
    resource = None  # type: ignore[assignment]

import duckdb
from groq import RateLimitError
from langchain_core.callbacks import get_usage_metadata_callback
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages

from src.agent.llm_provider import get_llm
from src.agent.pricing import estimate_cost_usd
from src.agent.prompts import ANALYSIS_TOOL_GUIDANCE, FORECAST_TOOL_GUIDANCE, build_system_prompt
from src.agent.rag.schema_index import assemble_schema_text, get_schema_index
from src.agent.router import classify_question
from src.config import settings
from src.db.connection import UnsafeQueryError
from src.tools.forecast_tool import execute_run_forecast, run_forecast
from src.tools.sql_tool import execute_run_sql, run_sql
from src.tools.stats_tool import execute_run_stats, run_stats
from src.tools.viz_tool import infer_chart_spec

logger = logging.getLogger("agent")

# Shown to the user (via router_node/agent_node's degraded-fallback path
# below, and re-exported for src/api/main.py's own defensive backstop
# catch) specifically when the underlying failure was a real
# groq.RateLimitError -- distinct from the generic "try rephrasing or
# ask again in a moment" fallback text, which is actively misleading for
# a real daily-quota exhaustion (DOCEXP.md's Slice 56/57: observed live,
# not hypothetical). Groq's SDK raises the same RateLimitError for both
# the per-minute and per-day cap, and there's no clean way to tell them
# apart here, so this is worded to stay honest either way -- a
# per-minute limit really does clear in well under a minute, and a
# per-day one needs tomorrow's reset.
GROQ_RATE_LIMIT_MESSAGE = (
    "Ludo has hit the AI provider's usage limit and needs a moment to recover. "
    "If this keeps happening, please check back tomorrow once the daily limit "
    "resets."
)


def _log_memory(label: str) -> None:
    # TEMPORARY diagnostic (Slice 49 follow-up, same as src/api/main.py's
    # copy -- duplicated rather than imported, since agent code doesn't
    # depend on the API layer, see this module's own docstring). Confirms
    # or rules out get_schema_index()'s first-ever construction (one
    # batch embed_texts() call over ~20 schema chunks, inside
    # retrieve_schema_node below) as the real memory-spike trigger,
    # narrowing down from the earlier finding that the semantic cache's
    # own single-query embed showed no measurable jump at all.
    if resource is None:
        return
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    logger.info("MEMORY [%s]: peak RSS so far = %.1f MB", label, peak_mb)


class AgentState(TypedDict):
    question: str
    messages: Annotated[list[BaseMessage], add_messages]
    attempts: int
    """Total tool-call round trips, success or failure -- a multi-step
    analysis question that legitimately needs two tool calls looks the
    same as one that needed a single retry. See `tool_errors` for the
    metric that actually means self-correction."""
    tool_errors: int
    """Incremented only when a tool call actually fails (the except branch
    in execute_tools_node) -- the real self-correction signal: a nonzero
    value means the model got something wrong and the graph fed the error
    back for it to fix, not just that the question needed multiple tools."""
    last_successful_sql: str | None
    last_successful_columns: list[str] | None
    last_successful_rows: list[list] | None
    last_stats_query: str | None
    last_stats_result: dict | None
    last_forecast_query: str | None
    last_forecast_result: dict | None
    retrieved_chunk_ids: list[str] | None
    route: str | None
    clarifying_question: str | None
    chart_spec: dict | None


def router_node(state: AgentState) -> dict:
    try:
        decision = classify_question(state["question"])
    except Exception:  # noqa: BLE001 -- same reasoning as agent_node's catch below
        # This is the exact class of gap Slice 42 found and fixed in
        # agent_node, but classify_question is a separate LLM call
        # (structured-output classification, not the tool-calling agent
        # turn) that had never gotten the same protection -- found while
        # auditing item 3 of the path-to-9/10 list ("production resilience
        # blind spot"), not hypothetically. Without this, a single router-
        # level hiccup (a rate limit, a malformed structured-output parse)
        # failed the entire request with a generic 503 at the API layer,
        # instead of the retry-then-degrade-honestly behavior agent_node
        # already gets for its own model call.
        time.sleep(settings.agent_retry_backoff_seconds)
        try:
            decision = classify_question(state["question"])
        except RateLimitError:
            # Both this call and the retry above hit the same real Groq
            # rate limit -- see GROQ_RATE_LIMIT_MESSAGE's own comment for
            # why that's told to the user honestly instead of the generic
            # "try again in a moment" text below, which undersells a real
            # daily-quota exhaustion.
            return {
                "route": "needs_clarification",
                "clarifying_question": GROQ_RATE_LIMIT_MESSAGE,
            }
        except Exception:  # noqa: BLE001 -- same reasoning as agent_node's catch below
            return {
                "route": "needs_clarification",
                "clarifying_question": (
                    "I ran into a repeated error trying to understand this "
                    "question. Could you try rephrasing it or asking again "
                    "in a moment?"
                ),
            }
    return {
        "route": decision.category,
        "clarifying_question": decision.clarifying_question or None,
    }


def route_after_router(state: AgentState) -> str:
    category = state["route"]
    if category in ("lookup", "analysis", "forecast"):
        return "retrieve_schema"
    return "ask_clarification"


def ask_clarification_node(state: AgentState) -> dict:
    question = state["clarifying_question"] or "Could you clarify your question?"
    return {"messages": [AIMessage(content=question)]}


_TOOL_GUIDANCE_BY_ROUTE = {
    "analysis": ANALYSIS_TOOL_GUIDANCE,
    "forecast": FORECAST_TOOL_GUIDANCE,
}


def retrieve_schema_node(state: AgentState) -> dict:
    _log_memory("before get_schema_index() (first call builds the index)")
    chunks = get_schema_index().retrieve(state["question"], top_k=settings.rag_top_k)
    _log_memory("after get_schema_index().retrieve()")
    schema_text = assemble_schema_text(chunks)
    # state["route"] is always set by the time this node runs (the router
    # always runs first, and needs_clarification never reaches this node) --
    # `or ""` just satisfies the type checker's Optional[str] on AgentState
    # without changing behavior; an empty-string key never matches anyway.
    tool_guidance = _TOOL_GUIDANCE_BY_ROUTE.get(state["route"] or "", "")
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
    # comparison via SQL, the concrete difference the router was built to
    # enable back in Slice 3. forecast: also gets run_forecast, a real
    # linear-trend projection over player_counts history (Slice 9b).
    if route == "analysis":
        return [run_sql, run_stats]
    if route == "forecast":
        return [run_sql, run_forecast]
    return [run_sql]


def agent_node(state: AgentState) -> dict:
    _log_memory("start of agent_node (tool-calling LLM turn)")
    llm = get_llm()
    retries_left = state["attempts"] < settings.sql_max_retries
    model = llm.bind_tools(_tools_for_route(state["route"])) if retries_left else llm
    try:
        response = model.invoke(state["messages"])
        _log_memory("after agent_node's model.invoke() succeeds")
        return {"messages": [response]}
    except Exception:  # noqa: BLE001 -- see the long comment below for why
        pass

    # execute_tools_node's try/except only catches a tool that ran and failed
    # (bad SQL, etc.) -- this is different: the model call itself never
    # produced a usable message at all. Confirmed for real, not hypothetical:
    # Groq has rejected this agent's own tool-call generation outright
    # (`groq.BadRequestError: Failed to parse tool call arguments as JSON`,
    # and separately `Tool choice is none, but model called a tool`), and
    # without this handling that crashed all the way up through run_agent(),
    # never reaching the self-correction loop, a real gap between "the tool
    # a query calls fails" (handled) and "the model's own turn fails"
    # (previously unhandled). Broad `except Exception` is deliberate here,
    # unlike execute_tools_node's narrower catch: unlike a tool call, there's
    # no portable exception hierarchy across providers to catch instead, and
    # every failure in this specific spot is equally unrecoverable without a
    # retry regardless of its exact type.
    attempts = state["attempts"] + 1
    tool_errors = state["tool_errors"] + 1
    # A same-instant retry is genuinely useful against a one-off malformed-
    # generation error, but close to useless against a real rate limit --
    # confirmed for real in Slice 44, growing the golden question set
    # reproduced this exact failure repeatedly, small token counts and
    # this node's own degraded-fallback text on question after question,
    # the signature of the retry landing in the same still-exceeded TPM
    # window as the original call. A few real seconds gives that window a
    # genuine chance to roll forward first.
    time.sleep(settings.agent_retry_backoff_seconds)
    try:
        # One retry with no tools bound -- forces a plain-text answer,
        # sidestepping the exact failure mode (malformed tool-call
        # generation) rather than risking it again.
        ai_message = llm.invoke(state["messages"])
        return {"messages": [ai_message], "attempts": attempts, "tool_errors": tool_errors}
    except RateLimitError:
        # Same reasoning as router_node's own RateLimitError branch: both
        # this call and the retry above hit a real Groq rate limit, so the
        # honest message says so instead of the generic "try again in a
        # moment" text below, which undersells a real daily-quota
        # exhaustion.
        degraded = AIMessage(content=GROQ_RATE_LIMIT_MESSAGE)
        return {"messages": [degraded], "attempts": attempts, "tool_errors": tool_errors}
    except Exception:  # noqa: BLE001 -- same reasoning as the first catch above
        degraded = AIMessage(
            content=(
                "I ran into a repeated error trying to answer this question and "
                "can't complete it right now. Please try rephrasing it or asking "
                "again in a moment."
            )
        )
        return {"messages": [degraded], "attempts": attempts, "tool_errors": tool_errors}


def route_after_agent(state: AgentState) -> str:
    last = state["messages"][-1]
    if getattr(last, "tool_calls", None):
        return "execute_tools"
    return "build_chart_spec"


def execute_tools_node(state: AgentState) -> dict:
    # This node is only ever reached via route_after_agent's "execute_tools"
    # branch, which only fires when the last message's tool_calls is
    # non-empty -- guaranteed to be the AIMessage that just requested a tool,
    # never a plain BaseMessage (which doesn't declare tool_calls at all).
    last_ai = cast(AIMessage, state["messages"][-1])
    tool_messages: list[ToolMessage] = []
    attempts = state["attempts"]
    tool_errors = state["tool_errors"]
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
            elif call["name"] == "run_forecast":
                result = execute_run_forecast(
                    call["args"].get("query", ""),
                    call["args"].get("horizon_days", 0),
                )
                update["last_forecast_query"] = call["args"].get("query", "")
                update["last_forecast_result"] = result
            else:
                raise ValueError(f"Unknown tool: {call['name']!r}")
            tool_messages.append(
                ToolMessage(content=json.dumps(result), tool_call_id=call["id"])
            )
        except (UnsafeQueryError, duckdb.Error, ValueError) as e:
            tool_errors += 1
            error_text = f"Error: {e}"
            if attempts >= settings.sql_max_retries:
                error_text += (
                    f"\n\nRetry limit ({settings.sql_max_retries}) reached. "
                    "You will not be able to call a tool again, give your final "
                    "answer now, explaining that the request could not be completed."
                )
            tool_messages.append(ToolMessage(content=error_text, tool_call_id=call["id"]))

    update["messages"] = tool_messages
    update["attempts"] = attempts
    update["tool_errors"] = tool_errors
    _log_memory("after execute_tools_node (SQL/stats/forecast execution)")
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
    graph.add_node("ask_clarification", ask_clarification_node)

    graph.set_entry_point("router")
    graph.add_conditional_edges(
        "router",
        route_after_router,
        {
            "retrieve_schema": "retrieve_schema",
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
    graph.add_edge("ask_clarification", END)
    return graph.compile()


_compiled_graph = build_graph()

# Human-readable progress labels for streaming, see stream_agent() below.
# Purely cosmetic (frontend display), never affects control flow.
NODE_PROGRESS_MESSAGES = {
    "router": "Classifying your question...",
    "retrieve_schema": "Retrieving relevant schema...",
    "agent": "Thinking...",
    "execute_tools": "Running query...",
    "build_chart_spec": "Preparing visualization...",
    "ask_clarification": "Checking your question...",
}


@dataclass
class AgentResult:
    answer: str
    sql: str | None
    columns: list[str] | None
    rows: list[list] | None
    stats_query: str | None
    stats_result: dict | None
    forecast_query: str | None
    forecast_result: dict | None
    retrieved_chunk_ids: list[str] | None
    route: str | None
    chart_spec: dict | None
    attempts: int
    tool_errors: int
    """Both surfaced on the final result (not just internal graph state) so
    the API response, logs, and /health can report real self-correction
    activity instead of it being invisible outside a debugger -- see
    DOCEXP.md's Slice 23 entry for why this was worth adding."""
    total_tokens: int
    estimated_cost_usd: float | None
    """Real token usage/cost for this one question's router+agent LLM
    calls, captured via get_usage_metadata_callback() around the graph
    invocation in run_agent()/stream_agent() -- the same mechanism and the
    same pricing source (src/agent/pricing.py) Slice 24 used to measure
    the numbers in README.md's "Measured results", now live on every real
    request instead of only visible when someone runs the eval suite by
    hand. See DOCEXP.md's Slice 26 entry."""


def _initial_state(question: str) -> AgentState:
    return {
        "question": question,
        "messages": [],
        "attempts": 0,
        "tool_errors": 0,
        "last_successful_sql": None,
        "last_successful_columns": None,
        "last_successful_rows": None,
        "last_stats_query": None,
        "last_stats_result": None,
        "last_forecast_query": None,
        "last_forecast_result": None,
        "retrieved_chunk_ids": None,
        "route": None,
        "clarifying_question": None,
        "chart_spec": None,
    }


def _strip_dashes(text: str) -> str:
    """The system prompt tells the model never to use an em dash or en
    dash, but that's a request, not a guarantee -- LLMs (especially a
    small, fast model like this project's Groq default) drift back to
    them anyway, confirmed by a real answer that came back with "Aseprite
    -- review score..." style dashes despite the instruction. This is the
    actual guarantee: a spaced dash ("word -- word", the common
    parenthetical-aside style an LLM reaches for) becomes a comma, since
    that's what the aside almost always means; a bare dash with no
    surrounding space (a tight numeric range like "10-20") becomes a
    plain hyphen instead, which is allowed. Also normalizes U+2011 (a
    "non-breaking hyphen" -- visually a hyphen but a distinct codepoint,
    found in the same live response that motivated this function, in
    "highest‑rated") to a plain ASCII hyphen: not literally an em or en
    dash, but the same class of "LLM reached for an unusual punctuation
    mark" problem, and a real one found by inspecting actual output, not
    hypothesized. Applied once, here, on the one path both run_agent() and
    stream_agent() funnel through, so every caller (the API, the MCP
    server, evals) gets the same guarantee without each needing its own
    copy of this rule.
    """
    text = re.sub(r"\s+[—–]\s+", ", ", text)
    text = text.replace("—", "-").replace("–", "-")
    return text.replace("‑", "-")


_SAFE_OUTLIERS_FALLBACK_COMMENTARY = (
    "This was checked against the rest of the dataset using a standard statistical "
    "outlier test."
)


def _render_outliers_fact_block(stats_result: dict) -> str:
    """Deterministically renders a real run_stats(mode="outliers") result as
    plain text. The model's own final answer never generates this sentence
    -- see ANALYSIS_TOOL_GUIDANCE -- specifically so the outlier list shown
    to the user can never be wrong: it's printed straight from stats_result's
    own data, not written by an LLM. Prompting the model to accurately
    restate this list failed twice for real (DOCEXP.md's Slice 58 and 59
    entries: a real, repeated hallucination naming an unverified extra
    "outlier" alongside the real one) -- this makes that specific failure
    structurally impossible instead of merely less likely."""
    threshold = stats_result.get("z_threshold", 2.5)
    outliers = stats_result.get("outliers", [])
    if stats_result.get("not_normal_enough"):
        # The tool itself already detected an implausible outlier count
        # (see stats_tool.py's _outliers(): a real z-score test predicts
        # outliers are rare, so a huge fraction clearing the threshold
        # means the column isn't distributed close enough to normal for
        # the test to mean anything -- not that dozens of real outliers
        # exist). Render the tool's own honest explanation, not a
        # generic "no outliers" message, which would misleadingly imply
        # the test ran cleanly and simply found nothing.
        return stats_result.get(
            "note", f"Statistical check (z-score threshold {threshold}): inconclusive."
        )
    if not outliers:
        return (
            f"Statistical check (z-score threshold {threshold}): no value in the "
            "dataset clears this threshold -- nothing here is a real outlier."
        )
    named = "; ".join(f"{o['label']} (z={o['z_score']:.2f})" for o in outliers)
    return f"Statistical outliers (z-score threshold {threshold}): {named}."


def _compose_outliers_answer(
    stats_result: dict,
    model_commentary: str,
    candidate_rows: list | None,
) -> str:
    """Combines the deterministic fact block above with the model's own
    (supposed-to-be name-free) commentary. `candidate_rows` is
    last_successful_rows -- a companion run_sql call's results, if the
    model made one to build a display table, the exact mechanism behind
    the real hallucination this whole design exists to close. This is a
    defensive backstop, not the primary mechanism: if the model's
    commentary still names a row from that companion query that isn't a
    real, tool-confirmed outlier -- prompt compliance isn't literally
    100% -- the commentary is swapped for a safe, generic, name-free
    fallback rather than surgically edited (simpler and more robust than
    trying to remove just the offending clause without leaving broken
    grammar behind), while the fact block above it, already guaranteed
    correct, is completely unaffected either way."""
    facts = _render_outliers_fact_block(stats_result)
    authorized = {o["label"] for o in stats_result.get("outliers", [])}
    commentary = model_commentary
    if candidate_rows:
        commentary_lower = model_commentary.lower()
        for row in candidate_rows:
            if not row:
                continue
            label = str(row[0])
            if label in authorized:
                continue
            if label.lower() in commentary_lower:
                commentary = _SAFE_OUTLIERS_FALLBACK_COMMENTARY
                break
    return f"{facts}\n\n{commentary}"


def _result_from_state(final_state: dict, usage_by_model: dict) -> AgentResult:
    final_message = final_state["messages"][-1]
    answer = (
        final_message.content
        if isinstance(final_message.content, str)
        else str(final_message.content)
    )
    answer = _strip_dashes(answer)
    stats_result = final_state.get("last_stats_result")
    if (
        final_state.get("route") == "analysis"
        and stats_result is not None
        and stats_result.get("mode") == "outliers"
    ):
        answer = _compose_outliers_answer(
            stats_result, answer, final_state.get("last_successful_rows")
        )
    total_tokens = sum(u.get("total_tokens", 0) for u in usage_by_model.values())
    return AgentResult(
        answer=answer,
        sql=final_state.get("last_successful_sql"),
        columns=final_state.get("last_successful_columns"),
        rows=final_state.get("last_successful_rows"),
        stats_query=final_state.get("last_stats_query"),
        stats_result=final_state.get("last_stats_result"),
        forecast_query=final_state.get("last_forecast_query"),
        forecast_result=final_state.get("last_forecast_result"),
        retrieved_chunk_ids=final_state.get("retrieved_chunk_ids"),
        route=final_state.get("route"),
        chart_spec=final_state.get("chart_spec"),
        attempts=final_state.get("attempts", 0),
        tool_errors=final_state.get("tool_errors", 0),
        total_tokens=total_tokens,
        estimated_cost_usd=estimate_cost_usd(usage_by_model),
    )


async def stream_agent(question: str):
    """Async generator yielding progress events, then exactly one final
    AgentResult. Used by the /ask/stream SSE endpoint so the frontend can
    show what the agent is doing (which node is running) instead of a bare
    spinner for however long the full graph takes.

    stream_mode="updates" yields {node_name: state_update} after each node
    finishes, every node function here is a plain sync function (agent_node,
    execute_tools_node, etc.), and LangGraph runs them in a worker thread
    under astream() without needing them rewritten as `async def`.
    """
    initial_state = _initial_state(question)
    final_state: dict = dict(initial_state)
    with get_usage_metadata_callback() as cb:
        async for update in _compiled_graph.astream(
            initial_state, stream_mode="updates", config={"run_name": "ask"}
        ):
            for node_name, node_update in update.items():
                final_state.update(node_update)
                if node_name in ("messages",):
                    continue
                message = NODE_PROGRESS_MESSAGES.get(node_name, node_name)
                yield {"type": "progress", "node": node_name, "message": message}

        result = _result_from_state(final_state, cb.usage_metadata)
    yield {"type": "final", "result": result}


def run_agent(question: str) -> AgentResult:
    initial_state = _initial_state(question)
    with get_usage_metadata_callback() as cb:
        final_state = _compiled_graph.invoke(initial_state, config={"run_name": "ask"})
        return _result_from_state(final_state, cb.usage_metadata)
