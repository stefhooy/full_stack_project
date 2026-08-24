# AI Game Analyst

A tool-using AI agent that answers plain-English questions about the video
game market by writing and running real SQL against a database it ingested
itself — not a fixed dashboard, not a chatbot answering from memory. This
is **Slice 1** of a larger project (see [PLAN.md](PLAN.md) for the full
roadmap and [DOCEXP.md](DOCEXP.md) for the engineering log/decisions).

## What's here right now

- A SteamSpy ingestion script that builds a local DuckDB catalog of ~200 games
- A read-only, guarded DuckDB connection — SELECT-only and row-capped,
  enforced by a real SQL parser in code, not by trusting the prompt
- RAG over the DB schema: table/column/metric descriptions are chunked,
  embedded, and retrieved per-question instead of always injecting the
  whole schema into the prompt
- A supervisor-router that classifies each question (lookup / analysis /
  forecast / needs-clarification) before any DB work happens, and routes
  forecast/ambiguous questions away from the SQL pipeline entirely instead
  of letting the agent guess
- A minimal LangGraph agent — `router` → `retrieve_schema` → `agent` →
  `execute_tools` loop — with one tool (`run_sql`) and a self-correcting
  retry loop (SQL errors get fed back to the model, up to 3 attempts)
- A FastAPI `POST /ask` endpoint wiring it all together, returning the
  answer, the SQL, the raw rows, the route classification, and which
  schema chunks were retrieved

## Setup

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
# then edit .env: set GROQ_API_KEY (free tier: https://console.groq.com/keys)
# EMBEDDING_PROVIDER defaults to "local" (fastembed, ONNX, in-process — no API
# key needed). First run downloads a small (~130MB) model, cached after that.
```

## Run it

**1. Ingest data** (one-time; re-running is safe, it won't duplicate rows):

```bash
python -m src.ingestion.ingest
```

Takes a few minutes — SteamSpy asks for ~1 request/second on the per-game
detail endpoint. Progress prints every 25 games. Raw API responses are
cached to `data/raw/`, so re-running after a partial failure resumes fast
instead of re-fetching everything.

**2. Serve the API:**

```bash
uvicorn src.api.main:app --reload
```

**3. Ask it something:**

```bash
curl -X POST http://127.0.0.1:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What are the 5 most-owned free-to-play games?"}'
```

### Example questions to try

- "What are the 5 highest-rated games with more than 1000 positive reviews?" (lookup)
- "What's the average price of games tagged as Action, and how does that compare to free-to-play games?" (analysis)
- "Which game has the highest peak concurrent player count?" (lookup)
- "How many players will this game have next year?" (forecast — routed to an honest "not supported yet")
- "Is this game good?" (needs_clarification — the agent asks which game instead of guessing)

The response includes the natural-language answer, the SQL the agent
actually ran, the raw rows it got back, and `retrieved_schema_chunks` — the
list of schema chunks the RAG retrieval step actually picked for this
question, so you can see retrieval working rather than take it on faith.

## Why the repo is structured this way

```
src/
  config.py       one typed Settings object; nothing else reads os.environ directly
  ingestion/       SteamSpy client + the ingest script
  db/               table schema + the read-only guarded connection (the safety boundary)
  agent/            LangGraph graph, router, prompts, the model-provider seam
    rag/              schema chunk corpus, embedding-provider seam, retrieval index
  tools/            run_sql today; stats/forecast/viz tools land in Slice 4
  api/              FastAPI — thin, only translates HTTP <-> agent
```

Each package maps to one layer of the eventual full architecture
(ingestion → storage → reasoning → tools → transport), so later slices
mostly *add* files to these packages instead of restructuring. A few
choices worth being able to defend:

- **`api/` depends on `agent/`, never the reverse.** The agent has to be
  runnable and traceable standalone, with no FastAPI import anywhere in
  its call path. That also means the eventual deployment target (Vercel
  Python functions vs. a separate Python host) is a decision that only
  touches `api/`, not the agent logic.
- **The SQL safety boundary lives in `db/connection.py`, not in the
  agent or the prompt.** `validate_select_only()` parses every query
  with a real SQL parser (sqlglot) and rejects anything that isn't a
  single SELECT against an allowlisted table, independent of whatever
  the LLM was told to do. The DuckDB connection is also opened
  `read_only=True` as a second, independent layer.
- **The self-correction retry loop is a visible graph node
  (`execute_tools` in `src/agent/graph.py`), not hidden inside a
  prebuilt LangGraph agent constructor.** I wrote the loop by hand
  specifically so every step is something I chose and can explain,
  rather than inherited default behavior from a library.
- **The model provider is one config value** (`MODEL_PROVIDER` in
  `.env`). `src/agent/llm_provider.py` is the only file that branches on
  it; the graph just calls `get_llm()` and gets back a LangChain chat
  model, with no idea whether it's Groq, Ollama, or (later) Gemini. The
  embedding provider (`EMBEDDING_PROVIDER`) gets the identical treatment
  in `src/agent/rag/embeddings.py` — a separate axis from the chat model,
  because Groq doesn't offer embeddings at all.
- **RAG retrieval is a visible graph node (`retrieve_schema`), not a
  step that happens before the graph runs.** Same reasoning as the
  self-correction loop being a real node: it shows up in LangSmith traces
  and is something to point at and explain, not implicit setup code.
- **The router uses structured LLM output (a Pydantic schema via
  `with_structured_output`), not a free-text prompt parsed by hand.**
  Guarantees the result is always one of exactly four valid categories,
  rather than guarding against the model inventing a fifth or wrapping its
  answer in prose.
- **`lookup` and `analysis` currently share the same backend** (the
  `retrieve_schema` → `agent` pipeline) — deliberately, since Slice 4's
  dedicated statistical-analysis tool doesn't exist yet. The
  classification is real and tested; giving `analysis` its own handler
  later is additive, not a rewrite of the router.

## Not in this slice (see PLAN.md)

Extra analysis tools, evals, caching, the frontend, and deployment are
all deliberately out of scope for Slice 3 — see PLAN.md for the full
roadmap.
