# PLAN — AI Game Analyst

*(See [ARCHITECTURE.md](ARCHITECTURE.md) for a diagram-first tour of what's
built so far, and [DOCEXP.md](DOCEXP.md) for the decision-by-decision log.)*

**Current slice: 9c complete → starting Slice 10 (Expo mobile client) next**

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
  Ollama for local dev. A Gemini seam exists in `src/agent/llm_provider.py`
  but is deliberately unfilled — decided against it as a fallback (free-tier
  keys expire too fast to be reliable for a portfolio demo)
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
- [x] Forecasting tool — NOT built this slice, as planned (no time-series data existed yet).
      Built in Slice 9b once player_counts (Slice 7) existed to project from.
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
- [x] Steam Web API `GetNumberOfCurrentPlayers` client (src/ingestion/steam_web_client.py) —
      public, no key needed (verified directly); handles both "no data" response shapes
      found empirically (result != 1, and a real 404 for a delisted app)
- [x] New `player_counts` time-series table + allowlisted for the agent + RAG corpus chunks —
      the agent could already answer player-count questions with zero changes to graph.py,
      exactly as promised by schema.py's "meant to grow" comment since Slice 1
- [x] Collection/materialization split (src/ingestion/poll_player_counts.py writes a
      timestamped JSON snapshot; build_player_counts_table.py rebuilds the table from all
      committed snapshots) — snapshots are irreplaceable history and get committed to git;
      the table itself stays derived/regenerable, same as `games`
- [x] Scheduled via GitHub Actions cron (`.github/workflows/poll_player_counts.yml`, every
      6h) — commits the new snapshot back to the repo
- [x] Resolved the "will SteamSpy ingestion be dynamic?" question from earlier: a second
      workflow (`refresh_catalog.yml`, weekly) pings the backend host's deploy hook, which
      rebuilds the Docker image and re-runs ingestion — no-ops cleanly until the secret is set
- [x] Dockerfile updated to materialize player_counts at build time too
- [x] Found and fixed a real bug (404s crashing the poll batch) and found-but-didn't-chase a
      real regression (adding a second "concurrent players" concept confused the local model
      about which table a column lives on) — quantified via the eval harness: 5/6 → 4/6
      deterministic, 4.3 → 3.7 avg judge score. See DOCEXP.md.

## Slice 8 — MCP server
- [x] Expose `run_sql`/`run_stats` as MCP tools (`src/mcp_server/server.py`) — reuses
      `execute_run_sql`/`execute_run_stats` directly, thin protocol adapter not a rewrite
- [x] `schema://games` MCP resource (reuses the RAG corpus's `assemble_schema_text`) so a
      client reads the schema up front instead of guessing
- [x] Local stdio transport (free: no hosting, no LLM key needed — the calling AI app
      brings its own model, the MCP server only exposes guarded tools)
- [x] Verified end-to-end with a real MCP client session (not just started and assumed
      working): tool discovery, resource read, a real query, and — critically — confirmed
      `DROP TABLE games` gets rejected through this path too, same guard as the agent uses
- [x] Documented Claude Code / Claude Desktop config in README.md, using `uv run
      --directory` so it doesn't depend on a client's config format supporting `cwd`
- [x] mcp SDK added to the `agent` extra in pyproject.toml (API differs from older/cached
      knowledge of the SDK — checked the installed version's actual API via introspection
      rather than guessing; `FastMCP` is now `MCPServer` in `mcp.server` as of mcp 2.1.0)

## Slice 9 — Frontend UI/design polish
- [x] Real visual identity: warm near-black/off-white grounds + a single amber
      accent, reusing the exact palette from ARCHITECTURE.md's agent-trace
      artifact so the live app and the docs read as one brand, not two
- [x] Typography: Archivo (display/UI) + IBM Plex Mono (data/code) — same
      pairing as the trace artifact, via `next/font/google`
- [x] Motion (motion.dev, the current name for Framer Motion) added as the
      app's one animation library — deliberately not also adding
      react-spring/Anime.js, which would just be redundant bundle weight;
      `MotionConfig reducedMotion="user"` wired in once, app-wide
- [x] Illustrated per-genre identity (`lib/genres.ts`, `components/GenreIcon.tsx`,
      `components/GenreShowcase.tsx`) — 8 hand-drawn SVG glyphs + the dataviz
      skill's already-validated 8-slot categorical palette (reused, not
      re-derived), assigned in real prevalence order counted from the actual
      200-game catalog (SteamSpy's `genre` field is comma-joined free text;
      "Early Access"/"Free To Play" excluded as non-genre tags, a handful of
      one-off non-game categories folded into "Other" per the palette's
      8-hue cap). Each card is a real example-question trigger through the
      existing `/ask/stream` path, not decorative.
- [x] Streamed progress re-rendered as `components/TraceSteps.tsx`, an
      animated node-by-node stepper matching the agent graph's real node
      names — the same visual language as the ARCHITECTURE.md trace, now
      appearing in the product itself, not just the docs
- [x] Verified in a real browser (Playwright, light + dark, hover states, a
      genre-card-triggered ask): found a real *backend* bug in the process —
      `/ask/stream` reliably crashed the whole Python process (native
      `OPENSSL_Uplink`/no-Applink fault, not a Python exception) on the
      first request that did real work. Root-caused and fixed in Slice 9b
      (it was never a code bug — see that slice's notes and DOCEXP.md); at
      the time this bullet was written the frontend's own handling of the
      resulting dropped connection (graceful error banner, no crash) had
      already been verified correct regardless.

## Slice 9b — Retro redesign + real forecasting
- [x] Visual identity overhaul: 80s-arcade-cabinet direction (chosen from 3
      concrete options — arcade/neon, terminal/phosphor, Y2K-futurism — the
      first Slice 9 pass had drifted toward a generic "safe SaaS" look).
      Sharp-cornered panels with pixel-corner HUD brackets, a single amber
      neon-glow accent (unchanged hex values — same amber as ARCHITECTURE.md's
      trace artifact), grounds realigned exactly to that artifact's palette
      (`#0d1014` dark / `#f6f4f0` light) rather than the earlier approximation
- [x] Four-typeface system, each with exactly one job: Archivo (body/UI),
      IBM Plex Mono (data/code, unchanged from Slice 9), Monoton (the hero
      headline only — neon marquee tube lettering), Press Start 2P (short
      pixel labels — eyebrows, badges, section headers; never body text)
- [x] A marquee chase-light animated border (CSS conic-gradient, `@property`,
      `prefers-reduced-motion`-guarded) on the ask console, and a genuine
      genre-card neon-glow-on-hover (box-shadow in the card's own hue, not a
      generic highlight) — the two places motion earns its keep, not motion
      everywhere
- [x] Real forecasting: `src/tools/forecast_tool.py` (`run_forecast`) — a real
      linear regression (scipy) over `player_counts` history, bound only for
      `forecast`-routed questions. `forecast` no longer routes to a hardcoded
      "not supported" terminal node — it flows through the same
      retrieve_schema → agent → execute_tools loop as lookup/analysis (see
      ARCHITECTURE.md's updated graph). The honesty constraint moved from the
      route level into the tool itself: fewer than 2 real snapshots for a
      game returns a structured "not enough history yet" result instead of a
      fabricated number, self-upgrading to a real projection (with an
      explicit low-confidence flag when the projection horizon dwarfs the
      observed history) the moment a second snapshot exists — no further code
      changes needed. Verified against real data: the actual catalog
      currently has exactly one player_counts snapshot, so this was verified
      taking the honest path for real, through a real Groq call, not just in
      a unit test
- [x] `/genres` endpoint (`src/db/genre_stats.py`) + the frontend's genre
      showcase switched from a snapshot hardcoded in `lib/genres.ts` (as
      built in Slice 9) to fetching live counts every render — raised
      directly by the user mid-session ("I don't want just 200 data
      timestamp, I want the retrieval to be dynamic"). Both the counts AND
      which genres make the top 8 now track the live catalog instead of
      drifting stale as `refresh_catalog.yml` re-ingests; curated per-genre
      icons/example-questions degrade gracefully (generic icon, templated
      question) for any genre outside the hand-curated set
- [x] Found and fixed a real, unrelated environment bug while chasing why
      `/ask/stream` couldn't be tested live: `uv`'s default-selected Python
      (3.14.2, its newest standalone Windows build) hard-crashes the whole
      process — not a Python exception — on ANY real TLS handshake
      (reproduced with plain stdlib `ssl`+`socket`, no project code
      involved). Root-caused by isolating layer by layer (stdlib ssl → bare
      requests → truststore-enabled requests, on both the venv's Python and
      an unrelated system Python) rather than guessing; fixed by pinning
      `.python-version` to 3.12 and rebuilding `.venv` — not a truststore bug,
      not an Avast bug (though Avast's cert interception is real and still
      why truststore is needed at all), a python-build-standalone Windows
      issue specific to the 3.14.2 build. See DOCEXP.md for the full
      isolation trail.

## Slice 9c — Markdown rendering, real genre browsing, ambient background
- [x] Fixed a real bug found while looking at Slice 9b's own screenshots:
      the answer panel rendered literal `**bold**`/`* item` markdown syntax
      instead of formatting it (`<p>{answer}</p>` never parsed markdown).
      `components/Markdown.tsx` wraps `react-markdown` with an explicit
      per-element `components` map (styled to this app's tokens, not a
      generic typography plugin) — bold, lists, code, links all render
      properly now
- [x] Genre cards now show the real games behind them. `GET /games`
      (`src/db/genre_stats.py`'s `get_games_by_genre`) — deterministic, no
      LLM call, same "fixed query, no guard needed" reasoning as
      `get_genre_counts()` — returns the actual top games for a genre
      (sorted by review score, then peak concurrent players). Clicking a
      card toggles a retro "leaderboard" panel (rank/name/price/review%/
      peak-CCU) instead of firing an LLM question; a secondary "ask the
      agent about {genre} →" link inside the panel still bridges into the
      existing `/ask/stream` flow for anyone who wants that
- [x] Ambient retro background (`components/RetroBackground.tsx`): a
      synthwave grid horizon + drifting pixel motes, animated with
      **Anime.js** — the one deliberate exception to "Motion is the only
      animation library," scoped specifically to an imperative, non-
      interactive ambient loop with no React state to synchronize with
      (Motion owns every state-driven UI transition elsewhere in the app).
      Kept faint (low opacity, `--accent`-derived color only) and skips
      starting entirely under `prefers-reduced-motion`. See DOCEXP.md for
      why this doesn't reopen the "one animation library" decision from
      Slice 9

## Slice 10 — Expo mobile client
- [ ] Same API, React Native/Expo UI — one codebase for iOS + Android
- [ ] Build/test locally via Expo Go (free) — no app-store publishing planned
      (Apple $99/yr, Google $25 one-time; skip unless explicitly wanted later)

## Dropped
- [x] ~~Gemini as a fallback provider~~ — decided against it (free-tier keys expire too
      fast to be a reliable fallback for a portfolio demo). The seam in
      `src/agent/llm_provider.py` stays in place (costs nothing to leave), just not filled in.
