# PLAN — AI Game Analyst

**Current slice: 6 complete → starting Slice 7 next session**

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
- [x] Statistical analysis tool `run_stats` (src/tools/stats_tool.py): describe (summary
      stats), compare_two_groups (real Welch's t-test + p-value + Cohen's d via scipy),
      outliers (z-score anomaly detection) — bound only for `analysis`-routed questions,
      finally differentiating analysis from lookup as flagged in Slice 3's DOCEXP entry
- [x] Visualization-spec tool `infer_chart_spec` (src/tools/viz_tool.py) — deterministic,
      not an LLM call; a new `build_chart_spec` graph node runs it after a successful
      run_sql result; `/ask` returns `chart_spec`
- [ ] Forecasting tool — deliberately NOT built this slice: no time-series data exists yet
      (Slice 7). Router's "not supported yet" response from Slice 3 stands; revisit once
      player_counts exists.
- [x] `/ask` also returns `stats_query` + `stats_result` for transparency
- [x] Tested all 3 stats modes directly against real data, then through the full graph,
      then live over HTTP; found and fixed a real type-coercion bug (z_threshold arriving
      as a string from Ollama's function-calling) and a real (unfixed, logged) small-model
      group-mislabeling bug — see DOCEXP.md

## Slice 5 — Eval harness
- [x] Golden question set (src/evals/golden_questions.py) — 6 questions across all 4 routes,
      reference facts computed LIVE from the DB at eval time, not hardcoded
- [x] Deterministic checks (src/evals/checks.py) — route correctness, numeric/text matching,
      and a targeted regression check for the Slice 4 group-mislabeling bug (a group labeled
      "free-to-play" must have ~$0 mean price by definition, or it's not actually filtered)
- [x] LLM-as-judge (src/evals/judge.py) — structured-output 1-5 factual-consistency score
      against the same reference facts, independent of the deterministic checks
- [x] Runnable as a regression check: `python -m src.evals.run_evals`, real exit code
      (0 only if every route + deterministic check passes; judge score is informational)
- [x] Validated against Ollama: 5/6 deterministic, 6/6 route accuracy, 4.3/5 avg judge score —
      the one failure is the known Slice 4 bug, caught identically by both signals
- [ ] Re-run against Groq once a key is available — open question from Slice 4 this was
      built to answer

## Slice 6 — Frontend + deploy
- [x] Resolved the hosting decision (open since Slice 1): Vercel for the frontend,
      a separate normal Python host (Render/Fly.io) for the backend — NOT Vercel
      Python functions, given this stack's real footprint (fastembed model, scipy,
      DuckDB, multi-step LLM calls). See DOCEXP.md for the reasoning.
- [x] Next.js frontend (`frontend/`) on the App Router: streamed progress (SSE),
      4 clickable example questions, chart rendering (Recharts, validated palette),
      a "Show the work" panel (SQL/retrieved schema)
- [x] `/ask/stream` SSE endpoint + `stream_agent()` — per-node progress events via
      LangGraph's `astream(stream_mode="updates")`, not token-level streaming
- [x] Semantic cache (`src/agent/cache.py`) — reuses the RAG embedding provider;
      similarity threshold calibrated empirically (0.93, not guessed) — see DOCEXP.md
- [x] Per-IP rate limiting (`src/api/rate_limit.py`) — in-memory sliding window
- [x] Graceful "high demand, try again" responses — real exceptions logged
      server-side, generic message to the client unless DEBUG=true
- [x] Deployment config: `Dockerfile` (ingestion baked in at build time) + `render.yaml`
      — written carefully but not verified against a live build (no Docker available
      in this environment); user to verify when deploying
- [x] Verified in a real browser (Playwright-driven, incl. dark mode) — found and
      fixed a real streaming/SSE parsing path end-to-end; diagnosed (not a bug) a
      subpixel-antialiasing screenshot artifact on small text, see DOCEXP.md
- [ ] Actual live deployment — user's to do manually (per their preference)

## Slice 7 — Live player-count time series
- [ ] Steam Web API `GetNumberOfCurrentPlayers` poller
- [ ] Scheduled via GitHub Actions cron
- [ ] New `player_counts` time-series table

## Slice 8 — Optional extensions
- [ ] Expose query tools as an MCP server
- [ ] Expo mobile client on the same API
- [ ] Gemini as a real fallback provider (fill in the seam in src/agent/llm_provider.py)
