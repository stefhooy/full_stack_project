# PLAN — AI Game Analyst

**Current slice: 3 complete → starting Slice 4 next session**

A tool-using analytical agent that answers plain-English questions about the
video game market with real analysis (SQL + stats + charts + narrative),
built one thin vertical slice at a time. Full destination architecture:
data-collection service (SteamSpy + Steam Web API) → DuckDB catalog +
player-count time series → RAG over the DB schema → supervisor-router →
specialized tools (SQL, stats, forecasting, viz, live-player fetch) →
self-correcting SQL loop → guardrails (read-only, allowlisted, row/time
caps enforced in code) → memory + semantic cache → eval harness + tracing →
web app → mobile.

Tech decisions already made (see DOCEXP.md for the "why"):
- Backend: Python + FastAPI
- Orchestration: LangGraph, hand-written nodes (no prebuilt agent chains)
- Tracing: LangSmith
- Model provider: single config value (`MODEL_PROVIDER`), default Groq;
  Ollama for local dev; Gemini seam reserved for later
- Database: DuckDB (local file to start)
- Frontend/deploy: Next.js on Vercel — deferred, hosting approach still open

---

## Slice 1 — Repo + ingestion + guarded DB + minimal self-correcting SQL agent + /ask

- [x] Repo structure: separate modules for ingestion, db, agent, tools, api
- [x] PLAN.md (this file) and DOCEXP.md created and kept current
- [x] README stub with run instructions
- [x] .env.example with placeholders (GROQ_API_KEY, LANGSMITH_API_KEY, MODEL_PROVIDER, etc.)
- [x] SteamSpy ingestion script: ~200 games, name/genre/price/review score/owners/playtime
  - [x] Respects ~1 req/sec rate limit on appdetails calls
  - [x] Caches raw responses to disk (data/raw/)
  - [x] Descriptive User-Agent
  - [x] Idempotent re-runs (UPSERT on appid, cache means no re-fetch)
- [x] DB layer: `games` table schema (src/db/schema.py)
- [x] Read-only guarded connection + query guard enforced in code (src/db/connection.py)
  - [x] Reject anything that isn't a single SELECT (real SQL parser, not regex)
  - [x] Table allowlist check
  - [x] Row cap enforced by rewriting the query's LIMIT
- [x] LangGraph agent: one tool (`run_sql`), schema-in-prompt (seam for RAG later)
  - [x] Self-correction loop as a visible graph node, up to SQL_MAX_RETRIES (default 3)
  - [x] Model provider read from config, swappable via `MODEL_PROVIDER`
  - [x] LangSmith tracing wired in (env-var based, no extra code needed)
- [x] FastAPI `POST /ask`: question in → answer + SQL + raw rows out
- [x] Full ingestion run (200 games) completed and verified
- [x] End-to-end test: real question through the running API
- [x] README run instructions verified + 3 example questions

## Slice 2 — RAG over the schema
- [x] Break the schema description into small chunks (table/column/metric_note)
- [x] Embed each chunk (swappable provider: local ONNX via fastembed, default; Ollama alt)
- [x] Visible `retrieve_schema` graph node: embeds the question, retrieves top-K by
      cosine similarity, assembles schema_text, builds the system prompt from it
- [x] Replaced schema-in-prompt (Slice 1's static full description) with retrieval
- [x] `always_include` tier for structurally-relevant chunks (table, name, genre) that
      pure semantic similarity under-ranks — found empirically, see DOCEXP.md
- [x] `/ask` returns `retrieved_schema_chunks` for transparency
- [x] Regression-tested against all 3 Slice 1 example questions + new RAG-specific ones

## Slice 3 — Supervisor-router
- [x] `router` node: classifies each question via structured LLM output
      (lookup / analysis / forecast / needs-clarification), now the graph entry point
- [x] lookup + analysis both route to the existing retrieve_schema -> agent -> execute_tools
      pipeline (same backend for now — Slice 4 gives analysis its own stats tools)
- [x] forecast routes to an honest "not supported yet" terminal node (no forecasting
      tool or time-series data exists yet)
- [x] needs_clarification routes to a node that asks a clarifying question back instead
      of guessing
- [x] `/ask` returns `route` for transparency
- [x] Tested all 4 categories end-to-end (classification + full graph + live HTTP)

## Slice 4 — Specialized analysis tools
- [ ] Statistical analysis tool (cohorts, significance, anomalies)
- [ ] Forecasting tool
- [ ] Visualization-spec generator tool

## Slice 5 — Eval harness
- [ ] Golden question set with known answers
- [ ] Scored + LLM-as-judge
- [ ] Runnable as a regression check

## Slice 6 — Frontend + deploy
- [ ] Next.js frontend on Vercel: streaming answers, charts, 3-4 clickable examples
- [ ] Semantic cache
- [ ] Per-IP rate limiting
- [ ] Graceful "high demand, try again" UX instead of raw errors
- [ ] Resolve hosting decision (Vercel Python functions vs. Vercel frontend + separate free Python host)

## Slice 7 — Live player-count time series
- [ ] Steam Web API `GetNumberOfCurrentPlayers` poller
- [ ] Scheduled via GitHub Actions cron
- [ ] New `player_counts` time-series table

## Slice 8 — Optional extensions
- [ ] Expose query tools as an MCP server
- [ ] Expo mobile client on the same API
- [ ] Gemini as a real fallback provider (fill in the seam in src/agent/llm_provider.py)
