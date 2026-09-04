# PLAN — AI Game Analyst

*(See [ARCHITECTURE.md](ARCHITECTURE.md) for a diagram-first tour of what's
built so far, and [DOCEXP.md](DOCEXP.md) for the decision-by-decision log.)*

**Current slice: 9g complete → starting Slice 10 (mobile-web polish + deployment) next**

A tool-using analytical agent that answers plain-English questions about the
video game market with real analysis (SQL + stats + charts + narrative),
built one thin vertical slice at a time. Full destination architecture:
data-collection service (SteamSpy + Steam Web API) → DuckDB catalog +
player-count time series → RAG over the DB schema → supervisor-router →
specialized tools (SQL, stats, forecasting, viz, live-player fetch) →
self-correcting SQL loop → guardrails (read-only, allowlisted, row/time
caps enforced in code) → memory + semantic cache → eval harness + tracing →
a responsive web app, deployed.

Tech decisions already made (see DOCEXP.md for the "why"):
- Backend: Python + FastAPI
- Orchestration: LangGraph, hand-written nodes (no prebuilt agent chains)
- Tracing: LangSmith
- Model provider: single config value (`MODEL_PROVIDER`), default Groq;
  Ollama for local dev. A Gemini seam exists in `src/agent/llm_provider.py`
  but is deliberately unfilled — decided against it as a fallback (free-tier
  keys expire too fast to be reliable for a portfolio demo)
- Database: DuckDB (local file to start)
- Frontend/deploy: Next.js on Vercel, FastAPI on a normal Python host
  (Render/Fly.io — resolved in Slice 6, see DOCEXP.md and README's
  "Deploying" section). No native mobile app — see "Dropped" below; the
  same responsive frontend covers phones instead.

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
- [x] ~~Re-run against Groq once a key is available~~ — superseded: Groq has
      been the active default provider for every slice since Slice 6, and
      Slice 24/27 both re-ran and published this exact eval against Groq
      for real (5/6 deterministic, the same known bug caught live again)

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
- [x] ~~Actual live deployment~~ — done for real in Slice 19, see README's
      "Deploying" section for the live URLs

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

## Slice 9d — Synthwave scene + cartridge genre picker
- [x] Replaced the faint amber-grid-on-neutral-black background with a full
      committed synthwave scene (`components/RetroBackground.tsx`): gradient
      sky, a striped glowing sun, low-poly mountain silhouettes, and a neon
      magenta perspective grid (converging verticals + Anime.js-animated
      scrolling horizontals) — built from a specific reference image, not a
      generic "retro" gesture
- [x] Dropped the light/dark theme split for brand chrome tokens in favor of
      one committed dark synthwave identity (`app/globals.css`) — a
      deliberate, explicit exception to the project's usual dual-theme
      discipline, permitted by the artifact-design skill's own "a design
      that deliberately commits to one visual world may stay single-theme"
      allowance. `--accent` stays the same warm gold used throughout the
      project (now also reads as "the sun's color")
- [x] UI panels became `.glass-panel` — translucent + backdrop-blur, so
      they read as floating over the scene rather than painted on top of it
- [x] Genre cards became genre **cartridges** (`components/
      GenreCartridge.tsx`): a real Game Boy-style chamfered-corner
      silhouette, a label-sticker window, and a connector-notch ridge,
      "ejecting" on hover (Motion spring). Found and fixed a real rendering
      bug in the process: CSS `clip-path` genuinely cuts the shape but
      paints no border along the new diagonal edge, so the chamfer was
      geometrically correct yet visually invisible — fixed by overlaying a
      stroke-only SVG polygon tracing the same cut, which is what actually
      draws the visible outline

## Slice 9e — Markdown formatting fix, real mobile-viewport testing
- [x] Fixed a real bug the user hit live: a `compare_two_groups` answer came
      back as raw `* **label:** value * **label:** value` text — literal
      asterisks, no real list. Root cause wasn't the renderer (react-markdown
      was already correctly parsing valid markdown since Slice 9c) — it was
      that the *model's own output* wasn't valid markdown at all: bullets
      chained on one physical line with no newlines between them aren't a
      CommonMark list no matter what parses them. Fixed at the source: added
      an explicit "Formatting your final answer" rule to
      `SYSTEM_PROMPT_TEMPLATE` (src/agent/prompts.py) instructing the model
      to use a real markdown table (GFM syntax) for ≥3 related numbers
      instead of inline bullets or a hand-drawn dash divider. Added
      `remark-gfm` to the frontend's `react-markdown` so a real table
      renders as a real `<table>` (styled to the app's tokens in
      `components/Markdown.tsx`) rather than needing the model to avoid
      GFM syntax it should be free to use. Verified live: the exact
      question that broke before now returns clean prose plus a real
      3-column table, confirmed rendered as an actual `<table>` in the
      browser (not text) with zero raw `**`/`----` anywhere
- [x] Real mobile-viewport testing (Playwright device emulation — iPhone 14,
      Pixel 7), not just assumed-fine from unchanged Tailwind responsive
      classes as the last two slices' "open questions" flagged. Found and
      fixed a real bug: the genre showcase's section header (`[ OR EXPLORE
      BY GENRE ]` + "live from the catalog") had no `flex-wrap`, so on a
      390px-wide viewport the two pieces overlapped/collided instead of
      wrapping. Confirmed no horizontal page overflow and no console errors
      across both device profiles after the fix

## Slice 9f — 1000-game catalog, craft/animation polish pass
- [x] Bumped `ingest_game_count` default 200→1000 (`src/config.py`,
      `.env.example`, `.env`) — 1000 is the free ceiling with the current
      ingestion code (SteamSpy's bulk listing returns ~1000/page, `ingest.py`
      only fetches page 0), not a real SteamSpy limit. Ran it for real:
      1000 games ingested, verified in the DB. Deliberately left the
      `Dockerfile`'s build-time default at 200 — that ingestion runs at
      Docker build time, rate-limited ~1/sec, so 1000 there means ~15 extra
      minutes on every future deploy build; documented as overridable via
      `--build-arg` instead of silently slowing deploys
- [x] Confirmed the Slice 9b/9c dynamic-genres design paid off exactly as
      intended: zero code changes needed for the genre showcase/leaderboard
      to reflect the new 1000-game distribution (top-8 genre order actually
      shifted — Strategy/Simulation now outrank Casual/Massively
      Multiplayer at this larger sample size)
- [x] Applied a concrete craft-audit pass grounded in Emil Kowalski's
      published animation/interaction principles (not vibes) — added
      `:active` press feedback (`scale(0.97)`, ~150ms ease-out) to the
      example-question chips, which had none before despite every other
      interactive element having it; unified all tap-feedback scale values
      to the same 0.97; added a subtle `blur(4px)→blur(0px)` transition to
      the progress-panel/result-panel swaps (Kowalski's "underrated" tip
      for smoothing rough transitions)
- [x] Real mobile-viewport re-verification (iPhone 14 + desktop) after both
      the data change and the animation changes — no overflow, no console
      errors, mobile genre-header fix from Slice 9e still holds

## Slice 9g — Full landing page rebuild: dev-tool identity, real 3D
- [x] Reversed the Slice 9/9b-9d retro-arcade direction after direct
      feedback it still read as "AI slop" — the honest diagnosis (see
      DOCEXP.md) is that a synthwave grid + neon glow + pixel font is
      itself a recognizable template trope regardless of execution
      quality. Removed `RetroBackground.tsx`, `GenreCartridge.tsx`, the
      Monoton/Press Start 2P fonts, the marquee chase-light border, the
      blinking cursor, and the scanline texture entirely — not toned down,
      gone
- [x] New direction, named by the user (linear.app) and grounded in what
      this product actually does rather than a decorative theme: near-
      black/off-white neutrals, one confident accent (kept the same warm
      gold used throughout this whole project — the one thread of
      continuity through the rebuild), Geist for UI/headlines (Vercel's
      font — distinctive without being a novelty display face), IBM Plex
      Mono kept for data/code. Real typographic hierarchy (size + weight)
      replaces the previous pass's glow/pixel-font signaling
- [x] Real 3D, not faked with CSS: added React Three Fiber + drei +
      `@types/three`. `components/HeroScene.tsx` — a single WebGL canvas
      (not one per card) with 6 lit primitive objects (icosahedron,
      octahedron, torus, box, capsule, cone) in the genre categorical
      palette, `MeshPhysicalMaterial` with clearcoat for a glossy/premium
      look, manual 3-light setup (no CDN-hosted HDRI environment — kept
      the project's no-external-asset discipline), gentle per-object
      rotation + a subtle mouse-parallax camera drift, all skipped under
      `prefers-reduced-motion`. Removed Anime.js (no longer has a job —
      R3F's own render loop replaced what it was animating)
- [x] Genre picker rebuilt as plain flat cards (icon + label + count),
      dropping the Game Boy cartridge silhouette from Slice 9d along with
      the arcade skin — kept the parts that were actually load-bearing
      (live per-genre data, the click-to-browse-real-games leaderboard)
      and dropped the decorative shape
- [x] Fixed 4 real React-Compiler-era lint findings surfaced by the new
      Three.js code (not suppressed): `Math.random()` in a render-path
      `useMemo` (impure) → replaced with a value deterministically derived
      from each object's index; mutating `camera` destructured from
      `useThree()` inside `useFrame` (flagged as mutating a hook's return
      value) → read `state.camera` from the `useFrame` callback parameter
      instead, which is the standard R3F-vs-React-Compiler-rules
      workaround; one-shot `useEffect`+`setState` for reading
      `prefers-reduced-motion` → replaced with `useSyncExternalStore`,
      which is also more correct (reacts live if the OS setting changes
      mid-session, which the old version didn't)
- [x] Full re-verification: build, typecheck, lint all clean; live-browser
      check (desktop + iPhone 14 emulation) of the hero, genre grid, a
      forecast result (still honest about insufficient history), and the
      genre-leaderboard flow — no console errors, no layout overflow
- [x] Found and recovered from an unrelated real regression mid-slice: the
      Python venv had somehow lost `pip`/`uvicorn` entirely between
      sessions (cause not fully diagnosed — possibly an interrupted
      external `uv` operation). Recovered via the same known-safe
      `uv sync --extra agent` rebuild used once before in this project

## Slice 10 — Mobile-web polish + deployment
- [ ] Further responsive-design pass beyond the Slice 9e bug fix — Slice 9e
      confirmed nothing is broken/overlapping on a real mobile viewport, not
      that the mobile experience has had the same design attention as
      desktop (touch target sizing, the cartridge grid's 2-column density,
      genre-leaderboard readability on narrow screens)
- [x] ~~Deploy for real~~ — done in Slice 19 (Render, not Fly.io — see
      that slice's entry for why); this was the resolved plan since Slice
      6 (see README's "Deploying" section for the concrete steps),
      executed by the user themselves (account creation, secrets) per
      their standing preference to handle external/billing-adjacent
      actions themselves

## Slice 11 — Steam storefront API enrichment + test suite
- [x] Investigated the "SteamSpy feels limited, should we switch APIs?"
      question for real instead of guessing: WebSearch-verified RAWG
      (20k free req/month) and IGDB (free via Twitch OAuth, 4 req/sec) as
      bigger, separate-scope catalog-broadening options for later; corrected
      the user's own proposed alternatives (Steam Web API's
      `GetPlayerSummaries`/`GetGlobalAchievementPercentagesForApp`/
      `GetNewsForApp`) — `GetPlayerSummaries` is Steam *user* profiles, not
      games, and the other two are too narrow/unstructured for this
      catalog. Recommended and built the smallest real win instead: Steam's
      own storefront API (`store.steampowered.com/api/appdetails`), a third
      distinct free API (alongside SteamSpy and the Steam Web API player-
      count poller), no new account/key needed
- [x] `src/ingestion/steam_store_client.py` — new client mirroring
      `steam_web_client.py`'s caching/rate-limit pattern (1.5s between
      calls, cached to `data/raw/storeapi_{appid}.json`, a distinct cache
      prefix from SteamSpy's own `appdetails_{appid}.json`)
- [x] 5 new `games` columns (`src/db/schema.py`): `release_date`,
      `release_date_raw`, `metacritic_score`, `platforms`, `categories`.
      `categories` is filtered through a curated 15-entry
      `CATEGORY_ALLOWLIST` in `ingest.py` — Steam's raw category list is
      ~30 tags, mostly controller/accessibility noise not useful for
      analysis questions
- [x] New pure parsing functions (`_parse_release_date`, `_parse_platforms`,
      `_parse_categories`) plus `_row_from_appdetails` updated to merge
      SteamSpy + storefront data; `run_ingestion` now calls both APIs per
      game. Real data quirk found and handled: Portal 2's live category
      list has two different `id`s (51 and 30) both labeled "Steam
      Workshop" — dedup by description, not id. Also: `platforms.mac` can
      be `false` even when `mac_requirements` text is present, so the
      authoritative `platforms.*` booleans are used, never inferred from
      non-empty requirements text
- [x] `src/agent/rag/schema_corpus.py` — 5 new schema chunks so the agent
      can actually use the new columns (the `metacritic_score` chunk
      explicitly warns NULL means "not scored," not "scored zero"; the
      `platforms`/`categories` chunks instruct `LIKE '%X%'`, not `=`, since
      both are comma-joined)
- [x] Full re-ingestion of all 1000 games with dual-API sourcing, old
      `games.duckdb` deleted and rebuilt from scratch (table is fully
      UPSERT-regenerable and gitignored, no migration needed)
- [x] First real checked-in pytest suite (`tests/`, 66 tests, 0 mocks of
      this project's own DB layer — real throwaway on-disk DuckDB fixtures
      instead, see `tests/conftest.py`'s docstring): the SQL guard
      (`test_sql_guard.py`, including a real end-to-end `DROP TABLE`
      rejection against a live fixture DB), stats/forecast/viz pure
      functions, the new ingestion parsing (using real captured Portal 2
      API response shapes, not invented fixtures), and genre-stats queries.
      `pyproject.toml` gained a `dev` extra (`pytest`, kept as an *extra*
      rather than a `[dependency-groups]` entry specifically so a bare
      `uv sync` still doesn't pull it in — consistent with the existing
      base/`agent` split) and `[tool.pytest.ini_options]` (network/LLM
      tests marked `live`, excluded by default)
- [x] Found and fixed one real test-authoring bug via actually running the
      suite, not fixed the code: a z-score outlier test with only 4 points
      failed because of a genuine small-sample "masking" effect (one
      extreme point drags the mean/stddev toward itself enough to lower its
      own z-score below the threshold) — correct statistical behavior, not
      a bug in `_outliers`; fixed by using 20 points instead of 4
- [x] `.github/workflows/test.yml` — runs the suite on every push/PR.
      Caught a real bug in my own first draft before finishing: it used
      `uv sync --extra dev` only, which would have failed in CI because
      `stats_tool.py`/`forecast_tool.py` import numpy/scipy from the
      `agent` extra, not base — fixed to `--extra agent --extra dev`
- [x] Caught a second real bug by actually re-running `uv run pytest -v`
      (the exact command README/CI use) instead of trusting the earlier
      passing run: `ModuleNotFoundError: No module named 'src'` — the
      plain `pytest` console-script entry point never adds the project
      root to `sys.path` (only `python -m pytest` does, via `-m`'s own
      cwd-insertion). Fixed with pytest's built-in `pythonpath = ["."]`
      ini option so `pytest`, `uv run pytest`, and `python -m pytest` all
      behave the same — would have silently broken CI too
- [x] ~~`poll_player_counts.yml`'s catalog-rebuild step costs ~2.5x more
      CI time than it needs~~ — it became a real problem (Slice 29: runs
      queuing up behind each other for hours) rather than staying
      theoretical, and got the narrower "appids-only" fix predicted here
- [ ] Real year-over-year forecasting (delta-players-per-year
      extrapolation, not just the existing short-window linear trend) needs
      historical yearly snapshots that don't exist yet from any free
      source. Proposed, not yet built or confirmed: convert the weekly
      `refresh_catalog.yml` re-ingestion into an append-only
      `owners_history` table (mirroring `player_counts`' accumulate-don't-
      overwrite pattern) so real yearly deltas accumulate over time

## Slice 12 — Naming Ludo, a "Meet Ludo" intro section, full catalog page
- [x] Named the agent **Ludo** (Latin *ludus*, "game, play") — user's choice
      from a set of offered options. Woven into the hero (`Ask Ludo a
      question.` + an italic etymology line) and the shared nav
      (`components/Nav.tsx`, new — one persistent header across both
      routes, added to `app/layout.tsx` so it doesn't need repeating per
      page)
- [x] New "Meet Ludo" scroll section (`components/MeetLudo.tsx`) between
      the hero's ask box and the genre showcase: a short explainer of what
      the catalog actually contains (naming the Slice 11 fields
      specifically — Metacritic, platforms, release date, feature tags,
      not just "more data"), plus 4 curated example questions that
      exercise those specific new fields (co-op + release year +
      Metacritic threshold + platform combination), distinct from the
      hero's existing review/stats/forecast-focused examples
- [x] `components/GamingObjectsScene.tsx` (new) — a second hand-authored
      React Three Fiber scene: a game controller, console, TV/monitor,
      disc, and cartridge, each built from grouped primitive geometries
      (drei's `RoundedBox` + core Three.js primitives), no external .glb
      assets, consistent with HeroScene.tsx's discipline. Deliberately
      NOT colored with the genre categorical palette — that palette is
      load-bearing elsewhere (which hue means which genre) and reusing it
      here as decoration would imply a mapping that doesn't exist.
      Extracted the shared `useReducedMotion` hook out of HeroScene.tsx
      into `lib/useReducedMotion.ts` once a second scene needed it
- [x] Real full catalog browse page at `/catalog`
      (`src/db/catalog.py` + `GET /catalog` + `app/catalog/`): search by
      name, filter by genre, sort by 7 different fields with correct
      NULL-last handling in both directions, pagination. `page.tsx` is a
      thin server wrapper (for a real per-route `<title>`, which a
      `"use client"` file can't export) around `CatalogClient.tsx`
- [x] Found and fixed a real sorting bug via the new test suite before it
      shipped: flooring NULL values to a low sentinel for sort purposes
      puts them last on descending order but *first* on ascending —
      not "always last" as intended. Fixed by sorting only the non-NULL
      rows and appending the NULL ones after, unaffected by sort
      direction, rather than trying to make one floor value work both ways
- [x] `tests/test_catalog.py` (9 tests, real `games_db` fixture, extended
      with real release dates on two rows specifically so the
      release-date sort test would be meaningful) — search, genre
      filtering, sort correctness (including the NULL-handling bug above),
      pagination, and the two edge cases (page past the end, sort key not
      in the allowlist) that a hand-built allowlist can't just trust to
      "not happen"
- [x] Real end-to-end verification via Playwright (chromium, not just unit
      tests): both routes, desktop + mobile viewports, zero console
      errors, zero horizontal overflow, search/genre-filter/sort/
      pagination all exercised against the live 1000-game backend and
      checked against the actual returned rows — plus a real visual bug
      found and fixed this way: the new 3D objects' chassis color
      (`--surface-raised`, the app's near-black panel color) was nearly
      invisible against the equally near-black canvas background, unlike
      HeroScene's saturated genre-colored objects. Fixed with a dedicated
      mid-graphite hex picked for this scene specifically, not reused from
      the 2D panel token
- [x] Catalog page container widened from the ask-flow's `max-w-2xl` to
      `max-w-7xl` after a first pass at `max-w-5xl` forced the 9-column
      table into a horizontal scroll on an ordinary 1440px desktop
      viewport — caught by actually looking at the rendered screenshot,
      not assumed fine because a scroll container existed
- [x] Full frontend re-verification before considering this done: `npm
      run lint` (caught and fixed one real error — a plain `<a href="/">`
      instead of `next/link`'s `<Link>`), `tsc --noEmit`, and `npm run
      build` all clean; both routes prerender as static content

## Slice 12b — Framer-inspired direction: turquoise accent, gradient blobs
- [x] User pointed at framer.com directly and asked to ditch the literal
      3D gaming-object scene for that site's ambient-background language,
      plus a turquoise+black palette. Scoped with two quick questions
      first rather than guessing: hero's existing abstract 3D shapes stay
      (only the controller/console/TV/disc/cartridge scene goes), and
      turquoise replaces the warm-gold `--accent` site-wide, not just in
      the new background — the genre categorical palette is untouched
      either way since it's load-bearing (which hue means which genre),
      not decorative
- [x] Deleted `components/GamingObjectsScene.tsx` outright (not kept
      behind a flag) — new `components/GradientBlobs.tsx`: 3 large,
      softly blurred (`blur(70px)`) turquoise-toned circles drifting
      slowly (Motion, frozen under `prefers-reduced-motion` via the
      already-shared `useReducedMotion` hook) behind the "Meet Ludo"
      copy, plus a faint SVG feTurbulence noise overlay so the blur
      doesn't band. Pure CSS/Motion, no WebGL — lighter than the R3F
      scene it replaces
- [x] `MeetLudo.tsx` restructured so the gradient sits behind the *whole*
      section (heading, copy, example chips) rather than confined to a
      small boxed illustration above the text — closer to how
      framer.com's own sections actually use this treatment (an ambient
      field behind content, not a separate diagram)
- [x] `--accent: #f0a63a` → `#2dd4bf` (turquoise) in `globals.css`,
      `--accent-contrast`/`--accent-glow` recomputed to match. Found and
      fixed one real piece of drift while touching this: `HeroScene.tsx`
      had one point light hardcoded to the old gold hex instead of
      reading `--accent` like every other accent consumer in the app —
      would have silently kept glowing gold after this change if not
      caught
- [x] Full re-verification: real backend + frontend dev servers, driven
      with Playwright (desktop + mobile) — zero console errors, zero
      horizontal overflow, a real `/ask` round trip screenshotted to
      confirm the route badge/bold-markdown/link colors all actually
      switched to turquoise (not just the token definition). `npm run
      lint`, `tsc --noEmit`, and `npm run build` all clean afterward.
      Killed both background dev servers this time before finishing —
      left one running after the previous slice and it blocked the
      user's own `uvicorn --reload` with a port conflict

## Slice 13 — "Roman Intelligence": a full light re-skin
- [x] Direct feedback ("the website is not nice at all") plus a full
      ChatGPT-generated design brief for a *different* fictional product
      ("PlayerLens AI," a game-studio internal analytics tool with churn/
      ARPDAU/monetization mock data, Roman-marble visual identity). Named
      the real conflict before writing any code rather than executing the
      brief verbatim: different product name, different data domain
      (Ludo answers public-market questions from a real Steam catalog;
      the brief's example content is fictional studio telemetry Ludo's
      backend can't produce), and a mocked `POST /api/agent` contract
      where Ludo already has a real one. Scoped with two questions before
      building: keep Ludo's name/backend/real data, adopt only the visual
      language (light, warm-ivory, serif+sans, restrained Roman motifs,
      royal-blue accent) — confirmed directly rather than assumed
- [x] New light design tokens (`globals.css`): warm ivory background
      (`#f8f7f3`), white floating-card panels with a two-layer soft
      shadow, royal-blue accent (`#1957ff`, replacing Slice 12b's
      turquoise less than a day after it shipped — a real, fast reversal,
      not something to paper over). Genre categorical palette untouched
      again, same reasoning as every previous accent change
- [x] Added a third type face: Instrument Serif for display headlines
      only (`--font-serif`, wired via `next/font/google` same as the
      existing two), Geist/IBM Plex Mono unchanged — the brief's own
      "ancient structure, modern intelligence" tension expressed as an
      actual typographic contrast, not just a mood board reference
- [x] Two hand-authored Roman motifs, no photographic assets (this
      project's standing discipline — see HeroScene/GamingObjectsScene's
      same rule — and the brief's own instruction that restraint beats
      literalism here): `components/icons/Laurel.tsx` (a simple sprig,
      flanking the hero eyebrow and dividing the capabilities row from
      the example questions) and `components/RomanArch.tsx` (one faint
      line-drawn arch-and-flutes shape in the hero background, opacity
      ~0.4 of an already-light border color). `components/icons/
      Medallion.tsx` — an abstract ring-and-ticks logomark replacing the
      plain text-only nav wordmark
- [x] Replaced the hero's 3D visual entirely: the saturated genre-colored
      abstract shapes (kept through Slice 12b) don't fit this elegant,
      restrained world — bright toy-block primitives next to a serif
      headline on ivory reads as a mismatch, not a style choice. New
      `components/HeroPreview.tsx` — a static floating panel showing a
      **real, previously-verified** Ludo answer (the same "5 highest-
      rated games" result confirmed live earlier this session), styled as
      the same panel the actual result view uses. Closer to the brief's
      own hero concept anyway ("a floating application panel," not a
      decorative illustration next to the text) — and it's honest, not a
      mockup
- [x] `MeetLudo.tsx` rebuilt again: Slice 12b's turquoise gradient-blob
      background doesn't fit the light re-skin either — replaced with a
      plain three-column capabilities row (Ask / Investigate / Show the
      work, mapped to Ludo's real router→retrieve_schema→agent graph from
      ARCHITECTURE.md, not a fourth invented capability just to match the
      brief's 4-item ASK/INVESTIGATE/EXPLAIN/ACT template), thin vertical
      rules between columns, a small laurel divider, and the same real
      Slice-11-grounded example questions as before
- [x] Deleted `HeroScene.tsx`, `GradientBlobs.tsx`, and
      `lib/useReducedMotion.ts` outright once nothing referenced them
      (confirmed by grep before deleting) — same "don't leave half-
      removed dead code" discipline as Slice 12b's scene deletion
- [x] Full re-verification against the user's own already-running dev
      servers (recognized via a port-6-recycled-but-untraceable-by-
      tasklist PID from the previous slice's cleanup mishap — didn't
      touch them, just pointed Playwright at the existing ports): both
      routes, desktop + mobile, zero console errors, zero horizontal
      overflow, a real `/ask` round trip screenshotted end to end. `npm
      run lint`, `tsc --noEmit`, `npm run build` all clean; backend's 76
      pytest tests re-run as a sanity check (untouched by this frontend-
      only slice, still green)

## Slice 14 — Dark again, illustrated, and louder about it
- [x] Direct rejection of Slice 13's light re-skin ("I dont like this
      design at all") plus four concrete new asks in one message: a dark
      animated black/green/turquoise background, a bolder "Apple style"
      font, a hand-illustrated classical figure wearing gaming headphones
      and holding a controller, and Roman-styled genre icons. Executed
      directly rather than re-asking — the asks were concrete enough this
      time, and the user had already been asked twice this session
- [x] `components/AuroraBackground.tsx` (new) — one fixed, full-viewport
      layer (not per-section) with a solid dark base fill plus 3-4 large
      blurred blobs (deep green + one brighter turquoise highlight)
      drifting slowly via Motion, `prefers-reduced-motion`-aware. Mounted
      once in `layout.tsx`; `body`'s own background is now transparent so
      the fixed layer shows through everywhere a `.panel`/nav/table
      doesn't already cover it with its own opaque fill
- [x] Recreated `lib/useReducedMotion.ts` (deleted at the end of Slice 13
      once nothing used it) — AuroraBackground needed the same hook again,
      real churn worth naming rather than hiding
- [x] `globals.css` back to a dark palette (reverting the mechanism, not
      just swapping color values — the light theme's floating-shadow-card
      look doesn't translate, so `.panel` dropped the shadow layer and
      went back to a flat hairline-bordered dark surface). `--accent` back
      to turquoise, named directly by the user again alongside the
      background hue
- [x] Font rebalanced rather than reverted: the hero H1 moved from
      Instrument Serif to bold, tight-tracked Geist ("more Apple style" —
      Apple's own marketing headlines are unambiguously sans, not serif).
      Instrument Serif demoted to the italic etymology caption and section
      sub-headings only — the one place a classical touch survives without
      fighting the hero's new boldness
- [x] `components/RomanGamerBust.tsx` (new) — a hand-authored SVG
      illustration: a classical profile-bust silhouette (a coin-cameo
      pose, chosen over a frontal face specifically because a profile is
      achievable convincingly with primitive bezier shapes and a frontal
      face isn't), a laurel wreath, over-ear gaming headphones, and a
      controller held at chest height with simplified rounded "hand"
      shapes. No external illustration/photo — same hand-authored-only
      discipline every visual asset in this app has followed since Slice
      9g. First layout attempt (bust behind, `HeroPreview` card overlapping
      it) hid almost the entire illustration including the controller —
      caught by actually looking at the screenshot, fixed by stacking the
      two vertically instead of overlapping
- [x] Genre icons given a "Roman medallion" treatment
      (`GenreShowcase.tsx`): circular (not square) icon chips with a
      colored ring border and an inset highlight, reading as a coin/
      medallion rather than redesigning each of the 10 hand-drawn glyphs
      individually — a consistent, cheap upgrade applied uniformly instead
      of 10 bespoke Roman-specific icons that risked losing
      legibility
- [x] Scroll-linked parallax added for real (not just on-mount fades):
      the hero's arch line-art and the bust illustration drift upward at
      different rates as the hero scrolls past, using Motion's
      `useScroll`/`useTransform` against the hero's own scroll progress —
      the concrete version of "add transitions when you scroll down."
      `MeetLudo`'s opaque section background also removed so the aurora
      shows through there too, not just in the hero
- [x] Full re-verification: `npm run lint`, `tsc --noEmit`, `npm run
      build` all clean; Playwright against both routes (desktop + mobile,
      the user's own already-running dev servers again, not new ones) —
      zero console errors, zero horizontal overflow, a real `/ask` round
      trip screenshotted; backend's 76 tests re-run, still green
      (untouched by this frontend-only slice)

## Slice 14b — A real hydration bug, and a statue instead of a bust
- [x] User hit a real, reproducible console error: Motion's "Target ref
      is defined but not hydrated" from `useScroll({ target: heroRef })`
      — a documented Motion/Next.js App Router hydration-timing class of
      bug, not something specific to a typo in this code. Fixed by
      dropping the ref-target form entirely rather than chasing the exact
      timing race: switched to `useScroll()` with no target (tracks raw
      `window.scrollY`) and rewrote the two parallax transforms
      (`useTransform(scrollY, [0, 700], ...)`) against pixel scroll
      position instead of ref-relative scroll progress. Verified fixed
      with a fresh (non-HMR) Playwright load plus repeated programmatic
      scroll events — zero console errors
- [x] User shared a real reference photo of a classical marble statue
      (raised arm, gold-draped cloth, curly hair) and asked to use it.
      Did not embed the photo — it's someone else's copyrighted
      photograph of a specific museum statue, and this app hand-authors
      every visual asset as code regardless (no exception for a
      user-supplied reference either) — but rebuilt the illustration to
      genuinely take its composition cues: `RomanGamerBust.tsx` (a
      shoulders-up profile) replaced by `RomanGamerStatue.tsx`, a
      front-facing standing figure with one arm raised holding the
      controller aloft (echoing the raised scepter), a diagonal gold
      drape across the torso, and fuller curled hair. Built from simple
      primitives (rects, ellipses, one rotated-rect arm with the rotation
      math worked out by hand) rather than freehand paths
- [x] Found and fixed a real first-draft bug in the new illustration by
      looking at the render, not by re-reading the transform math: the
      first version used two separately-rotated arm segments (upper arm +
      forearm) whose pivots didn't agree with each other, so the
      controller ended up floating disconnected above the hand instead of
      held in it. Fixed by simplifying to one rotated arm segment with
      the pivot/endpoint math actually computed (not guessed), then
      positioning the hand and controller at that computed endpoint —
      simpler geometry that's actually correct beat more detailed
      geometry that wasn't
- [x] Re-verified: `npm run lint`, `tsc --noEmit`, `npm run build` all
      clean; Playwright fresh-load + scroll check confirms the hydration
      error is gone; desktop + mobile screenshots confirm the controller
      now visibly connects to the raised hand

## Slice 14c — A real photo, verified and licensed, not a hand-drawn stand-in
- [x] User asked for genuine photographic realism ("a realistic statue of
      Apollo"), which a hand-drawn SVG structurally cannot deliver.
      Scoped with one question first, since the answer changes the whole
      approach: use a real, properly-licensed public-domain/CC photo
      (verified per-file, not assumed) vs. the user sourcing an image
      themselves vs. staying fully hand-drawn. User chose the first —
      breaking this project's hand-authored-only asset rule (held since
      Slice 9g) for the first time, deliberately and with the tradeoff
      named up front, not silently
- [x] Sourced the Apollo Belvedere (Vatican Museums) via Wikimedia
      Commons, but verified the *specific file's* license page directly
      before using it rather than trusting a search-result summary —
      confirmed CC BY 2.5, attributed to photographer Marie-Lan Nguyen,
      requiring attribution wherever the derived image is shown
- [x] Downloaded the actual image and looked at it before deciding how to
      use it (not assumed suitable sight-unseen): the source photo is
      full nudity, standard for classical statuary but not what a product
      hero image should show. Cropped to head/shoulders/extended-arm only
      — the same bust/torso framing convention already used for this
      app's own reference imagery — which also happens to keep the
      extended arm and hand (needed for the controller) in frame
- [x] `frontend/scripts/compose-apollo-hero.py` (new, checked into the
      repo — not a throwaway scratch script): downloads the source photo
      fresh, crops it, draws gaming headphones (ear cup + bezier-curve
      band) and a controller directly onto the photo with Pillow
      (`ImageDraw`/`alpha_composite`), adds a soft edge fade so the photo
      blends into `AuroraBackground` instead of showing a hard rectangle,
      downscales for web, and exports `public/apollo-hero.webp`. Source
      JPEG isn't committed (re-downloaded on demand, gitignored) — only
      the final derived asset is tracked
- [x] Found and fixed two real bugs by looking at the actual render, not
      by re-reading the code: (1) the controller, positioned near the
      photo's original right edge, rendered clipped off-frame — fixed by
      padding the canvas with transparent space before compositing;
      (2) the fade-mask logic then assigned the fade as the *entire* new
      alpha channel, which silently turned that same transparent padding
      back into opaque black — fixed by combining the fade with the
      pre-existing alpha channel via `ImageChops.darker` (per-pixel min)
      instead of replacing it outright
- [x] Replaced `RomanGamerStatue.tsx` (the hand-drawn illustration from
      Slice 14b) in the hero with the real photo via `next/image`
      (`priority`, real descriptive alt text — this is meaningful content
      now, not decorative), plus a small visible attribution caption
      under the image linking to the CC BY 2.5 license text, satisfying
      the license's actual requirement rather than treating attribution
      as optional. Deleted the now-unused component outright, consistent
      with this project's standing "no half-removed dead code" rule
- [x] Re-verified: `npm run lint`, `tsc --noEmit`, `npm run build` all
      clean; Playwright confirms zero console errors/overflow on both
      routes, desktop + mobile, plus a real `/ask` round trip; backend's
      76 tests untouched and still green. Also re-ran
      `compose-apollo-hero.py` standalone (fresh download, not the cached
      scratch copy) to confirm the script is actually reproducible from
      the repo, not just correct once in a temp directory — byte-identical
      output confirmed

## Slice 15 — Full restart: the real catalog is the identity, not a motif
- [x] Direct instruction to rebuild the landing page from scratch, remove
      the small laurel "eyelash" flourish, and pick whatever direction is
      most fitting. Ran this through the newly installed superpowers
      brainstorming skill: classified as Bounded (reshapes an existing
      page, not a new subsystem), asked one clarifying question that
      mattered (keep the Roman/aurora/statue identity and rebuild the
      execution, or start over with a different concept), got "start
      over" back before writing any code
- [x] The concept: the product's own real 1,000-game catalog, plotted
      live, is the hero visual, not a decorative motif on top of the
      product. `components/CatalogField.tsx` (new) fetches 100 real
      games from the same `GET /catalog` endpoint the browse page uses,
      plots price against review score, sizes each point by real peak
      concurrent players (log-scaled), and colors it by the game's real
      genre via the existing categorical palette
- [x] Paired with a real aesthetic risk taken deliberately: zero
      decorative accent color anywhere in UI chrome (`globals.css`
      dropped `--accent`/`--accent-contrast`/`--accent-glow` entirely) so
      the genre palette on real data points is the only color on the
      whole site. Every consuming component (buttons, pills, links, the
      trace stepper, markdown bold/links) rebuilt to a plain near-black/
      off-white monochrome instead
- [x] Deleted outright, once nothing referenced them: `AuroraBackground.tsx`,
      `RomanArch.tsx`, `icons/Laurel.tsx`, `icons/Medallion.tsx`,
      `public/apollo-hero.webp`, `scripts/compose-apollo-hero.py` (and its
      gitignore entry) — the whole Roman/aurora/statue identity from
      Slices 13 to 14c, gone in one turn on direct instruction, not
      trimmed or kept half-referenced
- [x] Two real bugs caught by looking at the actual render, not the code:
      (1) `CatalogField`'s dots threw `<circle> attribute cy: Expected
      length, "undefined"` on every point — mixing a static `cy` JSX
      attribute with an animated `cy` inside Motion's `animate` object
      left no defined starting value for Motion to interpolate from;
      fixed by moving `cy` fully into `initial`/`animate` and removing
      the static prop entirely. (2) The initial scatter showed hard
      vertical stripes of stacked dots because many real games share an
      exact price ($0, $19.99); fixed with a deterministic per-point
      jitter hashed from each game's own name (not `Math.random()` during
      render, consistent with this project's standing rule), stable
      across re-renders instead of reshuffling on every one
- [x] New explicit constraint mid-slice: no em dashes or en dashes
      anywhere on the site. Fixed every hardcoded UI string across the
      whole frontend (grep-verified, not spot-checked), but the real find
      was that the agent's own LLM-generated answer text came back with a
      live em dash despite a new system-prompt rule asking it not to
      ("Aseprite – review score...") — a prompt instruction to an LLM is
      a request, not a guarantee. Added a deterministic sanitizer,
      `_strip_dashes()` in `src/agent/graph.py`, applied on the one path
      both `run_agent()` and `stream_agent()` funnel through so every
      caller (API, MCP server, evals) gets the same guarantee. Found and
      fixed a real bug in the sanitizer itself before shipping it (a
      tight numeric range like "10–20" was being turned into "10, 20," a
      list instead of a range, because the regex's `\s*` matched
      zero-width gaps too) by requiring real whitespace (`\s+`) around a
      dash before treating it as a parenthetical aside. Also found and
      fixed a related, distinct character while checking the live
      output: U+2011 (a "non-breaking hyphen," not literally an em or en
      dash but the same class of problem), normalized to a plain hyphen
      too. Six new tests in `tests/test_graph_dash_stripping.py`
- [x] Verified via superpowers' verification-before-completion skill: `npm
      run lint`, `tsc --noEmit`, `npm run build` all run fresh in the same
      turn as the completion claim (not assumed from an earlier run);
      backend's now-83 tests fresh and green; a grep across the whole
      frontend for all three dash characters confirms zero hits outside
      code comments; Playwright fresh-run confirms zero console errors
      and zero horizontal overflow on both routes, desktop and mobile;
      a live curl against the running backend confirms the actual model
      output now contains none of the three dash characters

## Slice 16 — Direct feedback on Slice 15, run through the new skills for real
- [x] "I dont like it" on Slice 15's strict monochrome/data-scatter
      identity, plus four concrete asks in one message: a Latin/Roman
      touch, a dark green background, a sliding film-strip animation of
      real game covers, and different genre icons/colors. Ran this
      through `superpowers:brainstorming` again (classified Bounded),
      and asked three targeted questions before writing code rather than
      guessing on all four at once: hotlink real Steam cover art or use
      placeholders, does the film strip replace the data scatter as hero
      or sit alongside it, and how far should "Roman touch" go this
      time given the full identity was deleted last round. All three
      came back as the recommended option
- [x] `components/FilmStrip.tsx` (new): real Steam cover art (the actual
      `library_600x900.jpg` asset each game's own store page uses),
      hotlinked live from Steam's CDN, verified reachable with a live
      curl before wiring anything up. Fetches 40 real games from the
      existing `GET /catalog` endpoint, slides them in an infinite loop
      (list duplicated once, `translateX` to -50%), framed with real
      film-strip sprocket holes (a repeating radial-gradient background,
      not a CSS/JS hack) and a double-rule bronze border, the one
      restrained "Latin touch" applied here rather than reviving the
      deleted aurora/statue/laurel system. `next.config.ts` gained a
      `remotePatterns` entry for Steam's CDN, the one remote-image
      source in this app (added `appid` to `src/db/catalog.py`'s
      `_CATALOG_COLUMNS` and the `/catalog` response to make this
      possible); a cover that fails to load drops out of the strip
      instead of showing broken
- [x] Deleted `components/CatalogField.tsx` outright once the film strip
      replaced it in the hero and nothing referenced it anymore
- [x] Brought back a real accent color (`--accent`, a muted antique
      bronze/gold), reversing Slice 15's "zero decorative accent"
      experiment after direct feedback that it didn't land. Restored
      accent usage across every component that had been flattened to
      monochrome: the Ask button, route/cached pills, forecast's
      projected number, markdown bold/links, the trace stepper's dots
      and connecting lines, and `MeetLudo`'s capability icons
- [x] Re-picked the genre categorical palette (the user asked directly
      for different genre colors) using the dataviz skill's actual
      validator rather than eyeballing hex values, against this app's
      new dark-green background (`#0a0f0b`) specifically, not the
      skill's generic dark chart surface. First draft (rust, teal, gold,
      wine, olive, and other earth tones) failed the validator
      repeatedly no matter how it was reordered, hues that close in
      angle can't clear the adjacent-pair floors. Fixed by spreading
      across the full hue wheel instead (a real, generalizable lesson
      about categorical palette design, not just this palette); the
      final 8-hue set passes every check (lightness band, chroma floor,
      adjacent CVD separation, the normal-vision floor, contrast)
- [x] Redrew all 10 genre icon glyphs in `GenreIcon.tsx` (the user
      disliked the old ones directly) with a thin engraved-medallion
      ring built into every glyph, a second, smaller "Latin touch"
      alongside the film strip's frame, rather than a separate wrapper
      element around each icon
- [x] Re-verified fresh: `npm run lint`, `tsc --noEmit`, `npm run build`
      all clean; backend's 83 tests still green (untouched by this
      frontend-only slice); the dash grep from Slice 15 re-run and still
      zero hits outside comments; Playwright confirms zero console
      errors and zero horizontal overflow on both routes, desktop and
      mobile; a real `/ask` round trip screenshotted with the restored
      accent visible in the actual result view

## Slice 17 — Bigger, faster, neon: refining Slice 16 on real approval
- [x] Direct positive feedback on Slice 16 ("much bigger improvement")
      plus four concrete refinements: a full edge-to-edge film strip, a
      new "professional but also gamer like" font, a neon green hue, and
      a hover animation on the film strip
- [x] `FilmStrip` widened to true full-bleed (`w-full`, no `max-w`/`px`
      wrapper) instead of the `max-w-4xl` container from Slice 16, and
      the fetched sample bumped from 40 to 60 real games so a wide
      viewport doesn't show an obviously short loop
- [x] Swapped the whole site's sans face from Geist to Rajdhani (Google
      Fonts) — a squarish, technical face with real esports/gaming-HUD
      lineage but clean enough mid weights to still work as body copy,
      not just a headline flourish. Kept IBM Plex Mono for data, kept the
      "one sans face, no second display font" rule from Slice 15
- [x] `--accent` swapped from Slice 16's bronze to a neon green
      (`#39ff88`), picked distinctly more saturated/bright than genre
      slot 6's muted green so chrome and genre identity stay visually
      distinct rather than coincidentally the same color
- [x] Real hover interaction on the film strip, done as a native CSS
      keyframe (`.filmstrip-track` in globals.css) rather than a
      Motion-driven animation specifically so hovering could pause it
      with `animation-play-state` and resume exactly in place — a Motion
      keyframe tween stopped and restarted the same way risks a visible
      jump, since restarting re-interpolates toward the same keyframe
      list rather than truly freezing. Verified programmatically (not
      just visually): confirmed the track's computed `transform` changes
      before hover, stays frozen for the whole hover duration, and
      `animationPlayState` reads `paused`. Added a per-cover Motion
      `whileHover` (scale + accent glow) on top of the pause, independent
      transforms on different DOM layers composing without conflict
- [x] Re-verified fresh: `npm run lint`, `tsc --noEmit`, `npm run build`
      all clean; backend's 83 tests untouched and green; Playwright
      confirms zero console errors and zero horizontal overflow on both
      routes, desktop and mobile; a real `/ask` round trip still clean

## Slice 18 — The film strip opens: a cartridge detail card, plus speed and border refinements
- [x] Feedback on Slice 17 asked for three things: click a cover to see
      that game's info in a "video game cartridge" popup with a close
      animation back to the strip, a faster slide, and a strip border on
      the top/bottom only (none on the sides)
- [x] Ran this through `superpowers:brainstorming`, classified Bounded;
      the design pitched a `layoutId` shared-element morph from the
      clicked cover into the cartridge, but that was dropped before
      writing any code once it became clear the strip's list is
      duplicated (`[...visible, ...visible]`, for the seamless loop),
      so two DOM nodes share the same `appid`/`layoutId` at once — a
      shared-layout morph across them is ambiguous about which node it
      animates from. Built a plain scale-plus-fade `AnimatePresence` pop
      instead, which has no such ambiguity
- [x] New `components/GameCartridge.tsx`: a rounded detail card shaped
      like a ROM cartridge (a ridged "connector" bar along the bottom),
      showing the clicked game's cover, name, genre, release date,
      Metacritic, platforms, price, review score, owners, and peak
      players — every field already present on the `CatalogGame` the
      film strip already fetched, so opening it makes no second network
      call. Closes via its X button, a click on the backdrop, or Escape
      (all three checked live with Playwright, not just the X)
- [x] Extracted `lib/formatGame.ts` (`formatDate`, `formatOwners`,
      `formatPrice`, `formatPlatforms`) out of `CatalogClient.tsx`,
      which had its own private copies of the same formatting, once the
      cartridge became a second real consumer that needed exactly the
      same logic — one shared source instead of two copies drifting
- [x] `FilmStrip`'s slide now pauses deterministically whenever a
      cartridge is open (`animationPlayState: selected ? "paused" :
      undefined` alongside the existing CSS `:hover` rule), not just
      while the pointer happens to still be over the strip, and resumes
      the instant it closes — verified programmatically via computed
      `animationPlayState` before/during/after, not eyeballed
- [x] Slide duration multiplier dropped from `visible.length * 2.2`s to
      `* 1.2`s per direct request ("a bit faster")
- [x] Strip's outer frame border changed from all four sides
      (`border: "3px double var(--accent)"`) to `borderTop`/
      `borderBottom` only, no left/right rule, per direct request
- [x] Re-verified fresh: `npm run lint`, `tsc --noEmit`, `npm run build`
      all clean; backend's 83 tests untouched and green; Playwright
      confirms the border computes to 3px top/bottom and 0px left/right,
      a click opens the cartridge, the X/Escape/backdrop-click paths all
      close it, the track's `animationPlayState` is `paused` while open
      and `running` after close, and zero console errors/horizontal
      overflow on both routes, desktop and mobile; grepped the new/
      touched files for em dashes, en dashes, and non-breaking hyphens —
      none found in rendered copy

## Slice 19 — Actually deployed, for the first time
- [x] Backend deployed to Render (free web service, Docker runtime,
      `master` branch, Frankfurt region). Build ran real ingestion
      (1000 games via SteamSpy + Steam store enrichment, ~32 minutes
      total, ~25 of which is the enrichment step's deliberate 1.5s/game
      rate limit) and the local embedding model download, exactly as
      the Dockerfile describes, this time actually verified against a
      live build rather than only reasoned about
- [x] Corrected the README's own deployment advice before using it:
      checked current terms and Fly.io removed its free tier for new
      accounts in 2024 (2 VM hour/7 day trial only, then a card is
      required); Render's free web service tier still needs no card.
      Used Render only, not "Render or Fly.io" as originally written
- [x] Health Check Path set to `/health` (the app's real endpoint) —
      not the dashboard's own greyed placeholder text (`/healthz`),
      which would have pointed Render's health monitor at a route that
      doesn't exist
- [x] Build Filters (Ignored Paths) added on Render: `frontend/**`,
      `*.md`, `.github/**` — without these, every frontend-only commit
      or doc update (most commits in this project's history) would
      trigger a full backend rebuild, including a full 25-minute
      re-ingestion, for zero reason
- [x] Frontend deployed to Vercel (Hobby, free), Root Directory
      `frontend`, one real env var (`NEXT_PUBLIC_API_BASE_URL`). Vercel
      auto-suggested importing 26 environment variables detected from
      `.env.example` files across the whole repo (25 backend-only vars
      with empty values, since the real `.env` is gitignored and never
      visible to it) — all 25 removed, keeping only the one the
      frontend actually reads
- [x] Real gap found and fixed: `CORS_ALLOWED_ORIGINS` was missing
      entirely from Render's environment, not just left at its default
      — the backend was deployed via "Add from .env" against a local
      `.env` that had never included that line (only `.env.example`
      documents it), so `src/config.py`'s built-in default of
      `http://localhost:3000` was silently active in production. Added
      it explicitly, set to the real Vercel URL, "Save and deploy" (not
      "Save, rebuild, and deploy" — an env-var-only change needs a
      container restart, not a full Docker rebuild plus a second
      25-minute re-ingestion)
- [x] Closed the loop and verified for real, against the live URLs, not
      just localhost: `curl` confirmed `/health` returns `db_exists:
      true` in production; an `OPTIONS` preflight against `/ask` with
      the real Vercel `Origin` header confirmed
      `access-control-allow-origin` echoes the Vercel URL specifically,
      not a wildcard or a stale localhost value; Playwright against the
      live Vercel URL (not localhost) confirmed real cover art loads,
      the cartridge opens/closes, `/catalog` renders real rows, and
      zero console errors/horizontal overflow at desktop and mobile
      viewports; a live `POST /ask` round trip against the deployed
      Render backend returned a correct answer with correct SQL and a
      markdown table, no em/en dashes
- Live URLs: `https://ai-game-analyst-api.onrender.com` (backend),
  `https://full-stack-project-sepia-nine.vercel.app` (frontend)

## Slice 20 — The answer used to render below two whole sections it had nothing to do with
- [x] Real UX bug reported after the deploy: clicking Ask gave no visible
      feedback near the input, and the result rendered all the way at
      the bottom of the homepage, past the entire Meet Ludo and genre
      showcase sections — confirmed by reading `app/page.tsx`, not just
      taking the report on faith
- [x] Moved the progress-trace/error/result block to render directly
      under the ask bar and its example-question pills, before Meet
      Ludo and the genre showcase, instead of after both
- [x] Added an explicit "Ludo is thinking…" label above the trace
      dots, so the loading state reads as "something is happening" at
      a glance, not just five grey dots
- [x] Added `scrollIntoView({ behavior: "smooth" })` on every `ask()`
      call, anchored to a ref that wraps the trace/result block — this
      matters because Meet Ludo's example questions and the genre
      showcase's leaderboard picks call the same shared `ask()`
      function from much further down the page; without the scroll,
      triggering a question from either of those would show its answer
      off-screen above the click, which is the same underlying bug in
      a different direction
- [x] A separate, much larger idea from the same feedback (a
      ChatGPT-style multi-turn chat thread, follow-up questions,
      cross-game comparison within a conversation) was deliberately
      NOT built this slice. Recommended against building it as scoped:
      the stated use case (comparing games) is already served by the
      existing stateless `run_stats` `compare_two_groups` tool in a
      single question, and full conversational memory would require
      teaching the router/prompts to resolve references across turns —
      real architecture work that trades away some of the project's
      actual differentiator (a stateless, easy-to-guardrail pipeline)
      for a feature the current tools mostly already cover. Logged as
      an open question below rather than silently dropped
- [x] Verified fresh: `tsc --noEmit`, `npm run lint`, `npm run build`
      all clean; Playwright against a real local backend confirmed the
      "Ludo is thinking" label and the trace panel are both visible in
      the viewport immediately after clicking Ask, with no scrolling,
      on both desktop and mobile; a second check confirmed triggering
      `ask()` from a lower section (a Meet Ludo/genre-showcase example)
      scrolls the page so the trace panel becomes visible, not just the
      main bar's own click; zero console errors; grepped the new copy
      for em/en dashes and non-breaking hyphens, none found

## Slice 21 — Portfolio/hygiene cleanup pass (in progress)
- [x] Added `render.yaml` to Render's Ignored Paths (alongside
      `frontend/**`, `*.md`, `.github/**`) — the Slice 19 doc-fix commit
      touched it and, not yet being ignored, triggered a real wasted
      rebuild; closed the gap so a future comment-only touch to it
      won't do that again
- [x] Removed `@react-three/fiber`, `@react-three/drei`, `three`, and
      `@types/three` from `frontend/package.json` — confirmed zero
      imports anywhere in `app/`, `components/`, or `lib/` before
      removing (leftover from Slice 14's since-deleted WebGL statue
      hero). `npm install` dropped 54 packages from the tree; `tsc
      --noEmit`, `npm run lint`, `npm run build` all still clean, build
      compile time visibly faster (1.3s vs 2.7s)
- [x] Added a root `LICENSE` file (MIT)
- [x] Added `.github/workflows/frontend-ci.yml` — lint, `tsc --noEmit`,
      and `build`, gated on `frontend/**` changes only (same
      don't-rebuild-what-didn't-change reasoning as Render's Ignored
      Paths). Verified by running the exact same three commands locally
      against a truly fresh `npm ci` install first, not just trusting
      the YAML — all three passed
- [x] Added ruff + mypy for the backend (`[tool.ruff]`/`[tool.mypy]` in
      `pyproject.toml`) and wired both into `test.yml`, before pytest.
      Deliberately not full-strict mypy (LangChain/LangGraph/DuckDB don't
      ship complete stubs); a moderate ruff rule set (`E, F, I, UP, B,
      BLE, RUF`) with DTZ left out on purpose (this codebase has one
      consistent naive-vs-aware datetime convention DTZ would flag as a
      bug). Fixed every real finding rather than blanket-suppressing:
      33 real ruff issues (line length, an unpacked-but-unused variable
      in two tests, `zip()` without `strict=`, a stale generic-class
      syntax, ambiguous-unicode false positives in the two files that
      exist specifically to contain literal em/en dashes) and 13 real
      mypy issues (two unguarded `fetchone()` results that could be
      `None`, four functions typed `list[list]` when DuckDB actually
      returns `list[tuple]`, an untyped `ChatGroq` API key, two
      LangChain `with_structured_output()` calls typed looser than they
      resolve at runtime, one dead `sys.exit(main() or 0)` pattern, one
      genuine typeshed gap). Re-verified with a real live `/ask` and
      `/ask/stream` round trip afterward, not just unit tests, since two
      of the fixes (the API key wrapper, an SSE-yielding helper
      extracted to fix a duplicated long line) touched real request
      paths
- [x] `run_evals.py` now runs automatically (Slice 27) — see below
- [x] README hook added (Slice 25) — see below
- [x] Quantified results gathered and published (Slice 24) — see below

## Slice 22 — A RAG retrieval eval, not just a final-answer eval
- [x] Went through `superpowers:brainstorming`, classified Bounded (an
      existing eval-harness pattern applied to a new target, not a new
      subsystem). Real discovery made before designing anything, from
      reading `schema_index.py`/`schema_corpus.py` rather than assuming:
      retrieval only calls the local embedding model, never Groq, so
      this eval is free and can run in CI on every push — unlike the
      rest of the eval harness, which needs real, cost/rate-limit-gated
      LLM calls and stays manual-only
- [x] `src/evals/retrieval_golden.py`: 15 hand-labeled questions, each
      paired with the specific schema chunks retrieval should surface —
      deliberately excluding the 4 `always_include` chunks (`table:games`,
      `column:name`, `column:genre`, `table:player_counts`) from every
      expected set, since those bypass ranking entirely and testing for
      them would prove nothing about whether the ranking algorithm
      itself is doing its job. Cross-checked every referenced chunk ID
      against the real corpus programmatically before trusting any of
      it — zero typos, zero accidental overlap with the always-include
      set
- [x] `src/evals/retrieval_eval.py`: `evaluate_retrieval(top_k)` runs
      the real `SchemaIndex.retrieve()` (not a mock) against the golden
      set, computes recall@k per question and overall, plus a report
      printer matching `run_evals.py`'s style
- [x] Measured before locking in a bar, not guessed: recall@8 (the real
      production `RAG_TOP_K`) came back **1.000** across all 15
      questions. Confirmed this wasn't a trivially-passing test by
      checking discriminating power at lower k first — recall@3 = 0.789,
      recall@1 = 0.522 — proving the eval genuinely distinguishes good
      retrieval from bad, and confirmed deterministic across repeated
      runs (no randomness in embedding computation) before treating 1.0
      as a real, reproducible baseline
- [x] `tests/test_retrieval_eval.py`: a real pytest test asserting
      recall@8 stays at the measured 1.0 baseline, wired into the
      existing `test.yml` CI job (no new workflow needed — it's just
      another test in `tests/`) — a future corpus edit, embedding-model
      swap, or `schema_index.py` change that degrades retrieval now
      fails CI instead of shipping silently
- [x] Found and fixed two small, unrelated ARCHITECTURE.md staleness
      bugs while checking whether it needed updating for this work: the
      System overview diagram's FastAPI node was missing `/catalog`
      (added several slices ago), and the RAG diagram said "~24
      SchemaChunks" when the real corpus has grown to 35. Also added
      `catalog.py` as a box next to `genre_stats.py` (both bypass
      `connection.py`, previously only one was drawn) and corrected the
      explanatory bullet to state their actual, slightly different
      safety reasoning rather than imply they're identical
- [x] Verified fresh: `ruff check`, `mypy src/`, and the full pytest
      suite (now 84 tests) all clean

## Slice 23 — Self-correction, made visible instead of invisible
- [x] `attempts` (total tool-call round trips) already existed in graph
      state but was never surfaced past internal state, and conflated
      two different things: a legitimate multi-step question needing
      two tool calls looked identical to a real error-triggered retry.
      Added a second counter, `tool_errors`, incremented only inside
      `execute_tools_node`'s except branch — the actual self-correction
      signal
- [x] Both counters now flow all the way through: `AgentResult` →
      `AskResponse` (so anyone hitting `/docs` sees real per-request
      numbers) → a request-level log line whenever `tool_errors > 0`
- [x] `src/api/run_stats.py`: a small in-memory aggregate tracker
      (same single-process pattern as `cache.py`/`rate_limit.py`,
      same documented multi-instance caveat), exposed via `/health` as
      `self_correction`: total real runs, how many needed at least one
      self-correction, and — the number that actually answers "does it
      work" rather than just "does it happen" — what fraction of those
      recovered with a real answer versus ran out of retry budget.
      Tracks the recovered/exhausted split as a true intersection
      counter, not two independent counts subtracted from each other,
      specifically to avoid a negative-count edge case if a run ever
      hit the attempts cap via a long legitimate chain with zero errors
- [x] Cache hits and hard provider failures (a Groq rate limit killing
      the whole request before the graph's tool loop ever runs)
      deliberately do NOT count toward these stats — verified live,
      not just reasoned about: a real 413 tokens-per-minute error from
      rapid live testing propagated to the existing `FRIENDLY_ERROR_MESSAGE`
      503 path exactly as before, and `/health`'s `total_runs` correctly
      did not increment for it
- [x] `tests/test_graph_tool_errors.py`: 4 new tests against
      `execute_tools_node` directly, real DuckDB fixture, real errors
      (an actual `DROP TABLE games`) — not mocked. Specifically proves
      the distinction the whole feature exists for: two successful
      tool calls in one turn leave `tool_errors` at 0
- [x] Verified fresh end to end, not just unit tests: started a real
      local backend, confirmed `/health`'s `self_correction` block and
      `/ask`'s `attempts`/`tool_errors` fields are both present and
      correct on a genuine live Groq round trip, confirmed the
      aggregate updates correctly across two real requests. `ruff
      check`, `mypy src/`, and the full pytest suite (now 88 tests)
      all clean

## Slice 24 — Real, quantified results, gathered rather than gathered-and-massaged
- [x] Verified Groq's real current on-demand pricing for `openai/gpt-oss-120b`
      live (`$0.15`/M input, `$0.60`/M output tokens) rather than assumed
      from training data, before computing any cost number
- [x] Confirmed `langchain_core.callbacks.get_usage_metadata_callback()`
      correctly aggregates real token usage across an entire graph run —
      including the router's `with_structured_output()` call, which
      doesn't normally expose raw usage on its parsed return value — by
      testing it against a real live `run_agent()` call first, before
      wiring it into anything
- [x] Wired real token/cost tracking into `run_evals.py` itself (not a
      disposable one-off script): `EvalRunResult` now carries real
      `token_usage` and `estimated_cost_usd` per question, computed only
      from the router+agent calls a real `/ask` caller actually pays
      for — the judge's own LLM call happens outside the tracked block
      on purpose, since it's eval-harness overhead, not part of what
      answering the question costs
- [x] Ran the real eval suite for real numbers, published exactly what
      came back rather than a cherry-picked or re-run-until-clean
      result: route accuracy 6/6, deterministic checks **5/6** (one
      real, honest failure — the exact free-to-play group-mislabeling
      bug class the Slice 4 check was built to catch, caught live
      again on this very run), avg judge score 4.2/5, avg latency 15.5s
      over 6 real full-graph runs (range 3.2s-37.1s — reported as a
      range, not just an average, given how few and how skewed the
      samples are), avg cost **$0.00057/question**
- [x] Real cache-hit demonstration against a live backend, not assumed:
      a genuinely different question correctly missed (true negative);
      a natural real-world paraphrase ("Which game costs the most out
      of everything" vs "What is the most expensive game") also
      **missed** — an honest, useful finding that the 0.93 similarity
      threshold is more conservative in practice than a casual
      assumption would suggest; a near-identical rewording correctly
      **hit**, confirmed via the exact log line. Reported the honest,
      nuanced finding (precise, no false positives observed, but
      conservative on structurally-different phrasing) instead of a
      single invented "hit rate" number with no real traffic to derive
      it from
- [x] A real, previously-unknown bug surfaced by this work, logged as
      an open item rather than fixed on the spot (scope discipline —
      this slice was about gathering numbers, not re-validating the
      golden set): `golden_questions.py`'s `forecast_not_supported`
      question's `reference_facts` text still says "this system has no
      forecasting tool or time-series data," which was true before
      Slice 9b's real `run_forecast` tool existed and is stale now —
      likely contributing to that question's own middling 3/5 judge
      score
- [x] Published the real numbers in README.md (a new "Measured
      results" section) and the full methodology/caveats in DOCEXP.md
- [x] Killed two stale `uvicorn` processes during this slice's live
      verification that `pkill -f "uvicorn src.api.main"` silently
      failed to stop — switched to finding the exact PID via `netstat`
      and `taskkill //F //PID` instead, since a stale process serving
      pre-change code masquerading as a fresh one is a real, repeatable
      trap in this environment (see DOCEXP.md)

## Slice 25 — A README hook, and a real production reliability finding along the way
- [x] Confirmed the GitHub repo is actually public before building any
      of this — a recruiter-facing hook is pointless work if the repo
      isn't visible to them at all
- [x] Added badges (GitHub's own live workflow-status badges for
      `test.yml`/`frontend-ci.yml`, not static claims — they actually
      reflect current CI state; MIT license; Python/Next.js), a
      one-line "try it live" call to action with the real Vercel URL,
      and a real screenshot up top, before the dense technical prose
- [x] The screenshot is a genuine live capture, not a mockup: Playwright
      drove the actual deployed site, asked a real question, expanded
      "Show the work," and screenshotted the exact real result panel
      element (not a manually-guessed crop region) — real route badge,
      real answer, real SQL, real retrieved schema chunk list, saved to
      `docs/live-demo.png`
- [x] A real production incident surfaced while capturing it, not
      induced deliberately: the live backend returned a hard 502 from
      *every* endpoint including `/health` for a stretch, then
      recovered on its own — diagnosed methodically (checked `/health`
      alone to isolate "whole service down" from "just `/ask` is slow,"
      confirmed via response headers that uvicorn itself came back
      before declaring it recovered) rather than just retrying blindly
      until it happened to work
- [x] Traced it to Render's free-tier spin-down being rougher than
      previously documented: the existing README caveat said "the
      first request after inactivity takes 30-60s" (implying a slow
      but successful response); what's actually observed is a hard 502
      during the boot window, not a queued slow one — corrected the
      existing caveat to match reality instead of leaving a claim that
      turned out to be more optimistic than what really happens
- [x] Verified fresh: all three new/changed badge URLs return real
      200s (not just pasted and assumed); the screenshot file is a
      reasonable 70KB; grepped the new copy for em/en dashes — none
      found (the root README has never been subject to the frontend's
      no-dash rule, same as every prior slice's docs work)

## Slice 26 — Token/cost logging, closed out for real on the live request path
- [x] Slice 24 wired real token/cost tracking into `run_evals.py`
      only — a real `/ask`/`/ask/stream` request still reported
      neither. Closed the actual gap rather than considering it done
      because the eval harness had it
- [x] Extracted the pricing constant and cost formula (previously
      living only inside `run_evals.py`) into a new shared
      `src/agent/pricing.py`, so the eval harness and the live agent
      compute cost identically from one source of truth instead of two
      copies that could quietly drift apart
- [x] `run_agent()`/`stream_agent()` (`src/agent/graph.py`) now wrap
      the graph invocation in `get_usage_metadata_callback()` — the
      exact mechanism Slice 24 verified against a real call before
      trusting it — and `AgentResult` carries real `total_tokens`/
      `estimated_cost_usd` for that one question, flowing through to
      `AskResponse` (visible per-request at `/docs`) same as
      `attempts`/`tool_errors` did in Slice 23
- [x] `RunStats` (`src/api/run_stats.py`) extended to also accumulate
      real cumulative tokens/cost across real (non-cached) runs,
      surfaced as a new `usage` block in `/health` alongside the
      existing `self_correction` block — `avg_cost_per_question_usd`
      now updates live from genuine production traffic, not just a
      Slice 24 one-off eval measurement
- [x] Added the actual log line the task asked for by name ("token/cost
      **logging** per request") — every real run now logs
      `usage: route=... total_tokens=... estimated_cost_usd=...`,
      unconditional (not gated on an error, unlike the self-correction
      log line, since cost is worth seeing on every request, not just
      failures)
- [x] Verified live end to end on both request paths: a real `/ask`
      call and a real `/ask/stream` call both returned correct
      `total_tokens`/`estimated_cost_usd` (cross-checked against Slice
      24's per-question cost range, consistent); `/health`'s new
      `usage` block correctly aggregated across a real request; the
      log line confirmed firing with real values by reading the
      backend's own log output, not assumed from the code
- [x] Re-ran the real eval suite after the `pricing.py` extraction
      (judge skipped to avoid unnecessary Groq spend on a refactor
      check) — same 5/6 deterministic result, same real failure
      reproduced again, confirming the refactor didn't change behavior
- [x] `ruff check`, `mypy src/`, and the full pytest suite (88 tests,
      unchanged — this was a refactor plus new production
      instrumentation, no new test file) all clean

## Slice 27 — `run_evals.py` actually running automatically, and a stale golden question retired
- [x] Clarified a real gap before fixing it: Slice 22 automated a
      *different* eval (RAG retrieval recall@k) in CI; Slice 24 only ran
      `run_evals.py` manually, once, to publish numbers. The actual
      golden-question answer-quality suite had never been wired into
      anything automatic — closed that gap directly rather than
      counting adjacent work as covering it
- [x] Removed the `forecast_not_supported` golden question instead of
      fixing its stale `reference_facts` (flagged in Slice 24) —
      forecasting depth isn't this project's focus for an AI-Engineer-
      targeted portfolio, and the honest tradeoff is real: the eval
      suite now has no dedicated `forecast`-route regression check.
      Recorded plainly, not glossed over
- [x] `.github/workflows/run_evals.yml`: scheduled daily (+
      `workflow_dispatch` for on-demand runs), deliberately not on every
      push/PR — this hits real Groq API calls per golden question, and
      Groq's free tier is rate-limited per-minute, not just billed;
      gating every commit during a multi-commit development day risks
      flaky rate-limit failures, not real regression signal
- [x] Builds its own small (`--count 100`) evaluation catalog first,
      since GitHub Actions runners are ephemeral and `data/db/*.duckdb`
      is gitignored — valid for this purpose specifically because
      `golden_questions.py` computes ground truth live from whatever DB
      exists at eval time (by design, since Slice 5), so a smaller,
      faster, self-consistent catalog checks the agent's reasoning
      exactly as validly as the real 1000-game one would
- [x] Verified the whole pipeline for real before trusting the
      workflow file: ran the identical two steps (small ingestion, then
      `run_evals.py`) locally against a throwaway `DUCKDB_PATH`
      (`/tmp/eval_verify`, never the real local catalog) — confirmed
      5/5 route accuracy, 4/5 deterministic (the same real mislabeling
      bug caught a third time, now across three different catalogs —
      strong evidence it's a genuine, consistent model behavior, not a
      dataset-specific fluke), and confirmed the real local 1000-game
      `data/db/games.duckdb` was untouched afterward
- [x] `ruff check`, `mypy src/`, full pytest suite (88 tests, unchanged
      — no new test file, this was a workflow + eval-data change), and
      a YAML syntax check on the new workflow file, all clean
- [x] Cleaned up three stale unchecked boxes from Slices 4/6/10 that
      pre-dated actual deployment and were never marked resolved once
      Slice 19 superseded them
- [x] `GROQ_API_KEY` repository secret added by the user — first manual
      trigger surfaced a real bug, fixed in Slice 28 below

## Slice 28 — The first real run of run_evals.yml found a real bug in it
- [x] First manual trigger of the new scheduled workflow hit a genuine
      `groq.RateLimitError` (429) mid-suite: Groq's free tier caps
      `openai/gpt-oss-120b` at 8000 tokens/minute (TPM), and this
      suite's own back-to-back golden questions — several using
      3000-4700+ tokens each — burst past that on their own, with no
      external traffic involved at all. A real production bug in a
      brand-new CI workflow, caught by actually running it rather than
      trusting the design
- [x] Fixed with two mitigations, not one: a proactive `SPACING_SECONDS`
      (5s) gap between golden questions to spread usage across the
      rolling window, plus a real `_call_with_retry()` backoff (15s,
      then 30s) around both the agent call and the judge call as a
      safety net for whenever spacing alone isn't enough
- [x] Redesigned away from an initial lambda-based retry wrapper once
      ruff's bugbear (B023, "function definition does not bind loop
      variable") flagged the closure-over-loop-variable pattern — rather
      than argue the immediate-invocation usage made it safe in
      practice, changed `_call_with_retry` to take the function and its
      arguments separately, removing the lambda (and the whole class of
      bug the lint rule exists to catch) entirely
- [x] Verified with a real run against a throwaway catalog (never the
      real local 1000-game one) after the fix: completed cleanly with
      no rate-limit errors, same 5/5 route accuracy and 4/5
      deterministic result — the known free-to-play mislabeling bug
      reproduced a fifth time now, across a fifth distinct catalog
- [x] `ruff check`, `mypy src/`, and the full 88-test pytest suite all
      clean; confirmed the real local catalog's row count (1000)
      unchanged after both verification runs

## Slice 29 — poll_player_counts.yml stuck queuing behind itself for hours
- [x] User-reported: GitHub Actions showed a scheduled `Poll player
      counts` run still "Pending" 7 hours after its trigger time, with
      a manually-triggered run stuck "In progress" for 7+ minutes on a
      step called "Rebuild the local catalog." Diagnosed by reading the
      actual workflow file and the two scripts it calls, not by
      guessing from the symptom
- [x] Root cause confirmed by tracing the real code: that step ran the
      *full* `ingest.py` (both SteamSpy's per-game `appdetails` at
      ~1/sec and Steam's own storefront `appdetails` at ~1/1.5s, for
      1000 games — a genuine ~40+ real minutes) purely so
      `poll_player_counts.py` could read `SELECT appid FROM games`
      afterward. That query only ever used the `appid` column — none of
      the ~40 minutes of enrichment work was for data this script reads
      at all. This is the exact issue an earlier slice had already
      flagged as a real risk ("a narrower appids-only ingestion path is
      the likely fix if this becomes a real problem") and left
      unaddressed until it actually did
- [x] Fixed at the source, not by increasing timeouts or the
      concurrency window: `poll_player_counts.py` now fetches its
      appid list directly from `SteamSpyClient.get_all_page()` — the
      same cheap, single-request bulk listing `ingest.py` itself starts
      with — instead of requiring a pre-built `games` table at all. No
      more DuckDB dependency in this script, and
      `poll_player_counts.yml`'s "Rebuild the local catalog" step is
      gone entirely, not just made faster
- [x] Verified the new appid-sourcing function directly against the
      real live SteamSpy API (not mocked): returned 10 real appids
      headed by `730`, the same game this project has independently
      confirmed as the top-owned/most-played title all session.
      Deliberately did not run a full `run_poll()` locally (would poll
      1000 real games at Steam's own 1-request/second rate limit, ~17
      real minutes, to verify code that wasn't touched) — scoped
      verification to the part that actually changed
- [x] `ruff check`, `mypy src/`, and the full 88-test suite all clean;
      confirmed no stray local files were left behind by the
      verification run
- [x] Confirmed on a real run, not just calculated: the user cancelled
      the old stuck/pending runs and manually triggered the fixed
      workflow. Run #3 **succeeded in 19m29s total** ("Poll live player
      counts" alone: 19m22s for all 1000 games) — matching the ~20
      minute estimate almost exactly, down from the roughly hour-long
      runs before this fix. "Commit the new snapshot" wrote a real new
      file (`data/player_counts_raw/2026-08-29T16-40-29Z.json`, 1004
      insertions) and pushed it automatically, confirming the whole
      pipeline — not just the appid-fetching change in isolation —
      works end to end on GitHub's own infrastructure

## Slice 30 — A real bug hunt that found the eval check was wrong, not the model
- [x] Started from a real trigger: a scheduled `run_evals.yml` failure
      (4/5 deterministic) on `analysis_action_vs_f2p_not_mislabeled`,
      the same check that's failed repeatedly since Slice 4. Diagnosed
      the actual root cause by reading `prompts.py` and
      `schema_corpus.py` rather than guessing: the base system prompt
      *and* the RAG-retrieved `metric:no_union` chunk both gave the
      model a concrete worked SQL example for "comparing two groups"
      directly, competing with `ANALYSIS_TOOL_GUIDANCE`'s instruction
      to prefer `run_stats` for exactly that question class
- [x] Fixed the competing guidance in both `prompts.py` (base template
      + `ANALYSIS_TOOL_GUIDANCE`, made directive rather than a soft
      preference) and `schema_corpus.py`'s `metric:no_union` chunk —
      removed the dangerous worked example, kept enough domain
      vocabulary ("Action games vs. free-to-play games") to avoid
      regressing the Slice 22 RAG retrieval eval (verified: a first
      draft dropped recall@8 to 0.967, a revised wording restored it to
      1.000 exactly)
- [x] Verified the prompt fix with real repeated runs before trusting
      it, not just one clean pass — and it didn't work: 2 real runs
      after the change still produced plain conditional-aggregation SQL
      instead of calling `run_stats`. Reported this honestly rather
      than declaring victory on a plausible-sounding fix
- [x] **The real discovery**: re-examined every SQL string this check
      has ever failed on, across Slices 24, 27, 28, and this slice's
      own verification runs (six instances). Every single one correctly
      filtered on `price_usd = 0` for the free-to-play group. The
      original Slice 4 bug (a group falsely labeled free-to-play
      without actually filtering on `price_usd = 0`) has never actually
      recurred — the check was failing purely because it hard-required
      `run_stats`'s `compare_two_groups` mode and never inspected
      `result.sql`/the real returned values at all when a different,
      equally-correct tool was used
- [x] Corrected the record: this project's own docs (README.md,
      PLAN.md, DOCEXP.md) described this across four prior slices as
      "the same bug reproduced N times" — that framing was wrong,
      built from pattern-matching a failing check rather than actually
      re-verifying the SQL each time. Named directly rather than quietly
      fixed
- [x] Fixed the check itself, not the model: `_check_action_vs_f2p_not_mislabeled`
      now accepts two valid paths — the original `run_stats`
      `compare_two_groups` result, or a plain-SQL answer whose
      free-to-play-labeled column's *actual returned value* is really
      ~$0. Checks real data, not which tool produced it or the SQL's
      text, so it can't be fooled by phrasing and directly serves the
      original anti-mislabeling intent regardless of tool choice
- [x] Kept the prompt/schema clarity improvements despite them not
      being the actual fix — they're still more correct guidance with
      no observed downside, just not sufficient on their own for a
      problem that, as it turned out, mostly didn't exist
- [x] Verified with a real full run against the real 1000-game local
      catalog after the check fix: **5/5 route accuracy, 5/5
      deterministic checks** — the first clean run this specific
      question has ever produced, because the check now correctly
      recognizes an answer that was actually right all along
- [x] `ruff check`, `mypy src/`, and the full 88-test pytest suite all
      clean throughout

## Slice 31 — Agent Execution Trace artifact rebuilt: real graph shape, dark-green identity
- [x] The interactive "Agent Execution Trace" Claude Artifact (linked
      from `ARCHITECTURE.md`) had gone stale: its `forecast_not_supported`
      node and edges depicted the pre-Slice-9b graph, before `run_forecast`
      existed, and its warm-amber/Archivo styling predated the product's
      own pivot to a dark-green/neon accent (`--accent: #39ff88`) and
      Rajdhani. Rebuilt rather than patched
- [x] Removed `forecast_not_supported` from the graph entirely — forecast
      now correctly routes through the same `retrieve_schema` → `agent`
      ↔ `execute_tools` → `build_chart_spec` loop as `lookup`/`analysis`
      (matching `src/agent/graph.py` exactly), not a separate dead end
- [x] Rewrote the "Forecast question" example's steps around the one
      genuinely real captured run (question, route, retrieved schema
      chunks, and final answer all real, from a live call against the
      deployed backend) rather than inventing a tool-call transcript.
      That real run shows the model answering directly from schema
      context without invoking `run_forecast`, an honest, worth-showing
      real behavior, not a fabricated "and then it forecasted" step.
      Tried for a fresh, tool-invoked capture first (5 real attempts
      against Groq, spaced to respect the rate limit, plus a check for a
      local Ollama fallback); all attempts hit real 429/503s or found no
      local daemon, so this is the honest result rather than a retry
      loop run to exhaustion for cosmetic content
- [x] Restyled the whole artifact on the live product's own real design
      tokens (`--background: #0a0f0b`, `--accent: #39ff88`, Rajdhani +
      IBM Plex Mono) instead of inventing a new palette — a single
      committed dark theme, matching the product's own deliberate
      choice not to split light/dark chrome. Kept semantic status color
      (error/degraded badges reuse the product's own `--danger` red)
      distinct from the brand accent, per the dataviz/artifact-design
      skills' guidance
- [x] Fixed a second, smaller staleness bug while in there: the
      retrieval panel's copy still said "~24 schema chunks," predating
      Slice 22's RAG corpus, which now has 35
- [x] Published as a new artifact (the user asked to "make a new
      architecture artifact") rather than overwriting the old one in
      place: `https://claude.ai/code/artifact/78ea93b6-b38e-4242-b4d6-ab60eae3b4ab`
- [x] Regenerated `docs/agent-trace.gif` for real rather than leaving it
      stale: installed Playwright as an ephemeral `uv run --with
      playwright` dependency (not added to `pyproject.toml` — a one-off
      capture tool, not a runtime/dev dependency), drove the new
      artifact's `lookup` example through all 8 real steps at 2x device
      scale, and assembled the frames into a GIF with Pillow (also
      ephemeral via `uv run --with pillow`). Verified by reading back
      individual captured frames, not just trusting the script ran
      cleanly — caught and fixed one real bug this way: a stray em dash
      in the new artifact's own footer credit line, against this
      project's repo-wide no-dash convention

## Slice 32 — The forecast example was showing a capability that has never actually worked live, and a real production health check
- [x] User pushback ("why did you include a forecast question, Ludo
      doesn't have a forecast capability") triggered a real check rather
      than a defense: `run_forecast` (`src/tools/forecast_tool.py`) is
      genuinely real code, correctly bound to the `forecast` route, with
      an honest linear-regression implementation that refuses to
      fabricate a projection without enough history. But it has never
      produced a working forecast for a real user hitting the live site
- [x] Root cause, found while independently checking `/health` for this
      slice's broader audit: **only 2 real player-count snapshots exist,
      ever, 5 days apart** (`data/player_counts_raw/`), and even those
      aren't visible to the live backend — `player_counts` is only
      materialized into the database at **Docker build time**
      (`Dockerfile`), and the live deploy hasn't rebuilt recently enough
      to have picked up either snapshot: live `/health` is still missing
      the `self_correction`/`usage` keys Slices 23/26 added
- [x] Removed the Forecast example from the Agent Execution Trace
      artifact entirely (user's explicit call over reframing or leaving
      it) — republished to the same URL, "Five real runs" corrected to
      "Four", all remaining example/node/edge references re-validated
      programmatically after the removal
- [x] Investigated the deploy staleness itself rather than just noting
      it: confirmed `.github/workflows/refresh_catalog.yml`'s weekly
      Render-redeploy-via-deploy-hook has had zero runs ever, but that's
      because it was only added on Aug 24 (a Monday) — its first
      scheduled Monday-03:00-UTC slot is Aug 31, still ahead, so it
      cannot be blamed for the current staleness yet. Separately, found
      that this exact "stale process serving old code" symptom already
      happened once before, during Slice 23 (named directly in that
      slice's own commit message), and was worked around rather than
      root-caused at the time
- [x] Could not fully diagnose from the repo side alone — genuinely
      needs the user to check the Render dashboard directly. Two
      concrete things to check, both plausible root causes: (1) whether
      Auto-Deploy is actually enabled on the service (vs. only ever
      updated by manual deploys, which fits the recurring-staleness
      pattern), and (2) whether the `DEPLOY_HOOK_URL` GitHub secret has
      ever actually been set (`refresh_catalog.yml` no-ops silently,
      green checkmark and all, if it hasn't)
- [x] **Resolved live**: user confirmed Auto-Deploy was already on, added
      `DEPLOY_HOOK_URL`, manually fired `refresh_catalog.yml` — confirmed
      via GitHub's own Actions API that it succeeded and triggered a real
      Render redeploy. The redeploy's own restart briefly looked like a
      new incident (a hung `/ask`, then a 502), diagnosed live rather
      than assumed broken: Groq itself answered in 0.92s (not degraded),
      the identical question worked locally in 9.75s (not a code
      regression), and a retry minutes later returned instantly with
      `cached: true` — the original request had actually succeeded
      server-side all along, just slower than the client timeouts used
      to test it (a real, one-time cold start on constrained free-tier
      CPU). A fresh, uncached question then completed in 9.97s, matching
      local performance, confirming the live system is genuinely healthy
      end to end on current code

## Slice 33 — A real gap the cold-start scare surfaced: no ceiling on the Groq client
- [x] The cold-start incident in Slice 32 resolved on its own, but
      exposed a real, separate gap: `ChatGroq(...)` in
      `src/agent/llm_provider.py` set no explicit `timeout`/`max_retries`,
      so a slow cold path or a genuinely degraded provider has no
      ceiling — confirmed via `ChatGroq.model_fields` that the library's
      own defaults are `request_timeout=None` (unbounded) and
      `max_retries=2`
- [x] Added two new settings (`groq_request_timeout_seconds=45.0`,
      `groq_max_retries=1`) in `src/config.py`, passed through in
      `llm_provider.py`. Worst case now bounded at roughly two attempts
      x 45s instead of an unbounded hang; documented in `.env.example`
- [x] Attempted to also get a fresh green CI run on `run_evals.yml`
      against current live code, per the user's own request — hit a
      real, different Groq limit instead: **200,000 tokens/day (TPD) on
      the on-demand tier**, `Used 199865, Requested 656`, not the
      per-minute (TPM) limit `SPACING_SECONDS`/`_call_with_retry`
      (Slice 27/28) already handle. A genuinely new, previously
      undocumented constraint, not a bug — this session's own testing
      that day (direct Groq pings, local agent runs, live production
      calls, the eval suite's own calls) plausibly used a meaningful
      share of it. Not retried immediately: with ~135 tokens of headroom
      left, an immediate re-run would almost certainly fail the same way
- [x] Verified the hardening change without spending any more of the
      day's Groq budget: confirmed no test in `tests/` calls real Groq
      (`ChatGroq`/`run_agent` don't appear anywhere in `tests/`), so the
      full suite could be re-run safely. `ruff check`, `mypy src/`
      (44 files), and `pytest -q` (88/88) all clean

## Slice 34 — Frontend CI's first real run found a real bug, in the CI config itself
- [x] "Frontend CI" (`frontend-ci.yml`) had zero runs since being added
      — not a bug, just no commit to `frontend/**` had landed since it
      was created. Made a real, deliberate trigger (a comment in
      `next.config.ts`) instead of just asserting it would work, and it
      failed for real: `app/layout.tsx(36,50): error TS2304: Cannot find
      name 'LayoutProps'`
- [x] Root cause, confirmed by reproducing it locally rather than
      guessing: `LayoutProps<"/">` is a Next.js-generated ambient type
      (typed routes), written to `.next/types` only after `next dev`,
      `next build`, or `next typegen` has run at least once. Every local
      `tsc --noEmit` this project ever ran had stale `.next/` artifacts
      already sitting on disk from a prior dev/build session, silently
      masking this. `frontend-ci.yml`'s job order (install → lint → type
      check → build) runs type check *before* the build step that would
      have generated it — a genuinely fresh checkout has no `.next/` dir
      yet when type check runs
- [x] Verified the fix before applying it: `rm -rf .next` locally
      reproduced the exact CI error; `npx next typegen` (a real Next.js
      16 command, generates only the route/page/layout ambient types,
      no full build) followed by `tsc --noEmit` succeeded clean. Added a
      "Generate route types" step to `frontend-ci.yml` between Lint and
      Type check
- [x] Verified the corrected sequence end to end from a clean state, not
      just the one failing step in isolation: `rm -rf .next`, then lint
      → typegen → type check → build, all four green, matching exactly
      what CI now runs

## Slice 35 — Fix confirmed, but the confirmation attempt itself hit a GitHub Actions gotcha
- [x] User clicked "Re-run jobs" on the failing run to check the Slice 34
      fix — it failed identically, same missing-`LayoutProps` error, with
      no "Generate route types" step anywhere in the log. Not a failed
      fix: GitHub Actions pins a `push`-triggered run's workflow-file
      content to the commit that originally triggered it. "Re-run" was
      replaying the pre-fix commit's snapshot of `frontend-ci.yml`, not
      the corrected one already sitting on `master`
- [x] A second, compounding issue found in the same breath: the fix
      commit itself only touched `.github/workflows/frontend-ci.yml`
      plus docs, nothing under `frontend/**` — so even a fresh push of it
      would never have self-triggered this `paths`-filtered workflow
- [x] Added `workflow_dispatch: {}` to `frontend-ci.yml`, matching the
      manual-trigger pattern the other two workflows already use, so a
      workflow-file-only fix can be verified on demand instead of
      depending on an unrelated frontend edit. Verified the YAML still
      parses correctly (`yaml.safe_load`) and re-ran the full clean-state
      sequence (`rm -rf .next`; lint, typegen, `tsc --noEmit`) once more

## Slice 36 — Slice 30's fix finally confirmed for real in CI, and the same re-run gotcha caught it once more
- [x] User re-ran `Answer-Quality Evals` via "Re-run jobs" and got a
      confusing 4/5 with the *old*, pre-Slice-30 failure wording
      ("expected a compare_two_groups stats_result, got None") on a SQL
      query that was actually correctly filtered. Confirmed via the
      GitHub Actions API (`head_sha`, `run_attempt: 4`) that this was the
      exact Slice 35 gotcha recurring in a second workflow: "Re-run jobs"
      was replaying the run pinned to `5f783fa` (19:04, the commit that
      *created* `run_evals.yml`), over two hours before the actual fix
      commit `4507500` (21:14)
- [x] Real bonus finding along the way: that run also confirmed the
      previous day's Groq daily token quota (Slice 33) had reset — the
      full suite ran end to end with zero rate-limit errors for the
      first time this session
- [x] Told the user to use "Run workflow" (a genuinely new run against
      current `master`) instead of "Re-run jobs" on the stale run — came
      back **5/5 route accuracy, 5/5 deterministic checks**, the first
      real, CI-verified (not just locally-verified) confirmation that
      Slice 30's eval-check fix actually works end to end

## Slice 37 — README rewritten for a recruiter hook, not an engineering diary
- [x] User feedback, direct: README.md (620 lines) was too long and
      didn't hook, dense engineering-justification prose (a ~130-line
      "Why the repo is structured this way" section, heavily qualified
      bullet-essays) was crowding out the pitch a recruiter or hiring
      manager actually needs in the first 30 seconds
- [x] Used `superpowers:brainstorming` (Bounded path) rather than just
      rewriting on instinct: presented a concrete outline in chat first,
      got explicit direction on the two real judgment calls (move the
      deep "why" content into ARCHITECTURE.md vs. cut it; target ~150 to
      200 lines vs. a more moderate trim) before touching the file
- [x] Checked repo cleanliness before assuming there was work to do
      there too: nothing junky is actually tracked (`desktop.ini`,
      `.mypy_cache`, `.pytest_cache`, `.ruff_cache`, `.venv` all correctly
      gitignored or simply never added), `data/`/`docs/` are already
      minimal and sensible. Nothing to restructure beyond the README
      itself
- [x] Rewrote README.md: a direct hook (what separates this from a
      chatbot-wrapper portfolio project, stated plainly in the first
      paragraph), 6 quantified "why this matters for an AI Engineer
      role" bullets replacing the old prose wall, the Measured results
      table kept prominent, a condensed Quickstart/Architecture/MCP
      server/Deploying, and a "More" section linking out to
      PLAN.md/ARCHITECTURE.md/DOCEXP.md/frontend's own README for anyone
      who wants the depth. 620 lines to 227
- [x] Moved the genuinely new, non-duplicate design points from the cut
      content into ARCHITECTURE.md's existing "Design choices, named"
      section (live-computed golden-question ground truth; the eval
      checking a fact the label implies rather than the model's prose;
      the LLM judge never gating CI's exit code; SSE per-node streaming
      over token-level streaming) instead of just deleting them
- [x] Fixed a real, previously-unnoticed inconsistency while rewriting:
      the old README's own example-questions list still described the
      forecast route as "routed to an honest 'not supported yet'",
      contradicting that same README's other two sections correctly
      describing `run_forecast` (Slice 9b) as real. Corrected to the
      actual current behavior
- [x] Verified every link and referenced command target actually exists
      before publishing: `PLAN.md`, `ARCHITECTURE.md`, `DOCEXP.md`,
      `frontend/README.md`, `LICENSE`, `.env.example`,
      `frontend/.env.local.example` all confirmed present; scanned the
      new file for em/en dashes (none) matching the project's own
      no-dash convention

## Slice 38 — README follow-up: a real tech-stack section, and a features framing over a pitch framing
- [x] Direct user feedback on the just-shipped Slice 37 README: add an
      explicit tech-stack section (backend/frontend/tooling), and rename
      "Why this matters for an AI Engineer role" to "AI Engineer
      Features" — a features list a reviewer scans, not a persuasive
      argument aimed at them
- [x] Added a "Tech stack" section between the hook and the features
      list, sourced from the real `pyproject.toml`/`frontend/package.json`
      manifests rather than written from memory: Python 3.12/FastAPI/
      LangGraph+LangChain/Groq/DuckDB/fastembed/scipy/sqlglot on the
      backend; Next.js 16/React 19/TypeScript/Tailwind v4/Motion/Recharts
      on the frontend; uv/pytest/ruff/mypy/ESLint/5 GitHub Actions
      workflows/MCP server under tooling
- [x] Renamed the section header only, kept the bullets themselves
      (already concrete, quantified feature statements, not abstract
      argument prose) rather than rewriting content that didn't need it
- [x] Verified: 244 lines (up slightly from 227, a real net addition, not
      padding), no em/en dashes introduced
- [x] Follow-up in the same slice: the user wanted the tech stack shown
      as visual badge "squares" (grouped, colored pills), not prose.
      Rebuilt it as shields.io badges grouped under real `###`
      subheadings (Languages, AI / Agent, Data, Backend, Frontend,
      Tooling and CI/CD) rather than bold-text-as-heading, fixing a real
      markdownlint warning (`MD036`) the bold-label version had
      introduced. Verified every logo actually renders (not just that
      the URL returns 200) by rendering a local HTML test page with all
      candidate badges through a real headless-Chromium screenshot before
      committing to the final list, caught and fixed one real inaccuracy
      this way: a "SQL" badge that only had a PostgreSQL icon available,
      misleading for a project that uses DuckDB, not Postgres, dropped
      rather than kept for the sake of having one more badge

## Slice 39 — Real Apple-style glass, a real animated 3D gradient, and two vendored/installed third-party libraries with real integration problems found and fixed
- [x] Native CSS/SVG "liquid glass" implemented first, exactly as
      specified: an SVG `#liquid-glass` filter (`feTurbulence
      type="fractalNoise"` into `feDisplacementMap`, defined once in
      `app/layout.tsx`) fed into `backdrop-filter`, with a plain
      blur+saturate value declared first as a Safari/Firefox fallback
      (they don't support an SVG filter reference inside
      `backdrop-filter`, and CSS discards the whole declaration, not
      just the unsupported part, if it doesn't parse). Applied to the
      ask bar and the sticky nav via a new `.glass` utility
- [x] User then asked specifically for two real third-party libraries
      instead of the native version on the Ask button, and a shadergradient-based
      animated background: checked both for real fit before integrating
      either, rather than assuming a GitHub link means "npm install and
      go"
- [x] **shadergradient**: a real npm/React package
      (`@shadergradient/react` + `@react-three/fiber` v9 + `three` +
      `three-stdlib` + `camera-controls`, ~20 packages, verified
      compatible with this project's real Next.js 16/React 19). Read the
      installed package's own shipped `.d.ts` for the real prop surface
      rather than guessing at shader parameters. First tuning pass
      (stock-bright colors, `brightness: 1.1`) made the hero's own body
      text nearly unreadable, caught with a real screenshot, not
      assumed. Fixed with two independent changes, not just one: dimmed
      and darkened the shader itself, and layered a semi-transparent
      radial-gradient scrim (darkest directly behind the text column,
      lighter at the edges) between the canvas and the page content, so
      text contrast doesn't depend on which exact animated frame is
      showing
- [x] **liquid-glass-js**: not an npm package at all -- plain
      `<script>` globals, `class Container`/`class Button` declared at
      the top level of a classic script. Read the actual source
      (`container.js`/`button.js`, fetched directly, not summarized)
      before integrating, and found real, concrete facts that changed
      the plan: `addChild()` re-parents whatever DOM element you hand
      it (a real React-reconciler crash risk if done to an existing
      React-owned node), the glass refracts a ONE-TIME `html2canvas`
      snapshot cached statically across every instance (not a live
      re-render), and it has no public destroy/cleanup method at all --
      the scroll listener its render loop registers on `window` is
      never removed
- [x] Given those real constraints, built `LiquidGlassAskButton.tsx` as
      its own component rather than wrapping the existing `<button>`:
      React owns exactly one empty mount `<div>` (a real
      `useRef<HTMLDivElement>`) and nothing else; the library's Button
      is constructed imperatively inside it, queried fresh via
      `querySelector` in each effect rather than threaded across
      effects as a stored class-instance ref (the pattern the newly-
      installed `eslint-plugin-react-hooks@7.1.1`'s stricter
      `react-hooks/refs`/`react-hooks/immutability` rules specifically
      flagged and required restructuring away from)
- [x] Vendored `container.js`/`button.js` under
      `public/vendor/liquid-glass/` with a real MIT `LICENSE` file
      (fetched the actual license text and copyright holder, not
      assumed), loaded in strict dependency order (html2canvas before
      container.js before button.js) by a new `lib/loadLiquidGlass.ts`,
      memoized so React Strict Mode's double-invoked effects don't
      double-inject scripts. `glass.css` moved into the real bundled
      source tree (`app/liquid-glass.css`, imported normally) rather
      than vendored as a static asset, since Next's own lint rule
      objects to raw `<link rel="stylesheet">` tags and a stylesheet
      has none of the script load-order constraints the two `.js` files
      do
- [x] Found and fixed a real bug during verification, not assumed
      working from the code alone: `window.Button` was always
      `undefined` even after all scripts loaded, because a top-level
      `class` declaration in a classic script creates a global lexical
      binding, not a `window` property (unlike `var`). Fixed with a
      small bridging inline script
      (`window.Container = Container; window.Button = Button;`) that
      runs in the same shared global scope. Caught by an actual
      Playwright run against the real dev server, not by reasoning about
      the code
- [x] Found and fixed a second real bug the same way: a naive
      `useEffect(..., [label])` meant to keep the button's displayed
      text in sync raced the async script-loading, and initial page
      load stuck on the sizing placeholder ("Asking…") instead of "Ask"
      until the user's first real state change. Fixed with ref-backed
      current values applied immediately after the button is actually
      created, not just synced on prop change
- [x] Found and fixed a real accessibility regression the switch away
      from a semantic `<button>` introduced: liquid-glass-js's generated
      element has no `tabindex`, `role`, or keyboard handling at all.
      Patched `tabIndex`, `role="button"`, `aria-label`/`aria-disabled`
      (kept in sync on every label/disabled change), and an Enter/Space
      keydown handler onto the generated element directly, with a
      `disabled` guard inside the activation function itself (not just
      a `pointer-events: none` style, which a keyboard press ignores
      entirely)
- [x] Verified end to end against a real local dev server (backend +
      frontend both actually running), not just lint/build: a real
      Playwright click through the actual liquid-glass button, through
      the real streaming `ask()` flow, to a real Groq-backed answer
      rendering, confirmed zero page errors and the button's text
      correctly cycling Ask -> Asking... -> Ask. Separately confirmed
      keyboard activation (tab to the button, real `role`/`tabIndex`/
      `aria-label`, Enter key) through the same shared activation path
- [x] `ruff`/`mypy`/`eslint`/`tsc`/`next build` all clean throughout;
      credited both libraries with real links and real explanations in
      `frontend/README.md` (which also had its own stale claim, "No
      WebGL/3D, no fixed animated background layer," fixed to match
      reality) and the root README's Tech Stack gained a verified
      Three.js badge

## Slice 40 — A real, confirmed-working forecast, and the real name-matching bug it exposed
- [x] User pushback, again, on the forecast feature: a real screenshot
      showed "How many players will Counter Strike have next year?"
      failing with a false "no historical live-player snapshots for that
      game" answer, plus a fair UX critique that the example-question
      pill "How many players will this game have next year?" is
      unanswerable as written (no game named) and "dumb" as a canned
      example
- [x] Rather than accept "the forecast tool doesn't work, remove it,"
      diagnosed the actual failure locally, with full visibility a
      screenshot alone can't give: reproduced the exact question against
      the real 24-snapshot local catalog, captured `tool_errors: 1` and a
      failed tool call
- [x] Found the real root cause by testing the literal SQL pattern
      `FORECAST_TOOL_GUIDANCE`'s own worked example teaches, directly
      against the DB, not by guessing: `name ILIKE '%Counter Strike%'`
      (a space) returns **zero rows** against the real title
      `'Counter-Strike: Global Offensive'` (a hyphen and colon) —
      `ILIKE` is a literal substring match, punctuation is never
      normalized. Not a data problem (the 24 snapshots for that game are
      real and correct), not a multi-row-ambiguity problem (first
      hypothesized, then disproven by testing) — a punctuation-mismatch
      bug in the guidance's own worked example
- [x] Verified a fix before writing it into the prompt: confirmed
      `REPLACE(REPLACE(name, '-', ' '), ':', ' ') ILIKE '%...%'`
      correctly finds all 6 real "Counter-Strike"-family games, then
      confirmed `ORDER BY peak_ccu DESC LIMIT 1` reliably picks the
      right one (730, 1,013,936 peak_ccu) over the other 5 (highest
      alternate: 7,323) — an order-of-magnitude margin, not a close call
- [x] Fixed the guidance in two places, not one: `column:name`'s schema
      chunk (`always_include=True`, read on every question regardless of
      route, so this benefits lookup/analysis too, not just forecast)
      and `FORECAST_TOOL_GUIDANCE`'s own worked example, both now
      teaching the verified normalize-then-disambiguate pattern instead
      of the naive one that seeded the bug
- [x] Re-ran the exact original failing question after the fix: real
      tool call succeeds (`tool_errors: 0`), correctly resolves to the
      right game, and for an intentionally unreasonable 365-day horizon
      from only ~11 days of history, correctly floors the projection at
      0 and honestly flags `low_confidence: true` with a specific
      reason, exactly the tool's designed behavior, not a new bug
- [x] Fixed the actual UX complaint too: replaced the vague example pill
      with a real, verified-working question using the catalog's real
      name ("How many players will Counter-Strike: Global Offensive
      have next month?"). Left `router.py`'s own "will this game have
      next month" line alone, it's a classification-pattern example for
      the router's intent recognition, not a user-facing question, a
      different and legitimate use of similar wording
- [x] Verified: `ruff`, `mypy`, full 88-test `pytest` suite, and the
      RAG retrieval eval (a schema chunk text change regressed this
      once before, in Slice 30) all clean/at-baseline after the prompt
      changes; frontend `eslint`/`tsc` clean after the example-question
      change

## Slice 41 — The live forecast staleness explained, and its actual root cause fixed
- [x] User saw the fixed forecast working live (Vercel-deployed frontend,
      Slice 40's real example question), but with "≈0 players" projected
      and only 8 snapshots/6.3 days of history, far less than the 24+
      snapshots/10.8+ days already accumulated by then. Explained the
      "0" first: a floored (`max(0.0, ...)`) negative-slope extrapolation
      from a weak fit (R²=0.063), not a real claim the game will have no
      players, exactly the tool's designed honesty under a bad trend,
      not a new bug
- [x] Traced the real staleness to its actual cause rather than treating
      it as expected: `refresh_catalog.yml` is the ONLY thing that ever
      triggers a Render rebuild (Vercel only serves the frontend and was
      already current), and it runs weekly, a schedule its own comment
      explains was chosen for slow-moving catalog facts (price,
      reviews) — but `player_counts` (fast-moving, added later in Slice
      7) shares that exact same trigger, so the live forecast tool could
      lag real accumulated history by up to 7 days
- [x] Checked Render's actual free-tier docs before recommending a
      cadence, rather than assuming more-frequent-is-free: build-
      pipeline minutes have an undisclosed monthly cap that bills for
      overage, unlike GitHub Actions minutes on this public repo, which
      are genuinely unlimited. Presented three real cadence options with
      that real cost tradeoff named, not just picked one
- [x] Changed `refresh_catalog.yml`'s schedule from weekly
      (`0 3 * * 1`) to daily (`0 4 * * *`), deliberately not matched to
      `poll_player_counts.yml`'s own 6-hour cadence — closes the
      staleness window from up to 7 days down to at most 1, at roughly
      30 real build-minutes/day rather than ~4x that. Verified the YAML
      still parses correctly (a `yaml.safe_load` check on a bare `on:`
      key returns `None` under PyYAML's own boolean-coercion quirk for
      `on`/`off`/`yes`/`no` — re-checked against `d.get(True)` instead
      of treating that as a real parse failure, GitHub's own Actions
      parser is unaffected by this Python-library-specific gotcha)

## Dropped
- [x] ~~Gemini as a fallback provider~~ — decided against it (free-tier keys expire too
      fast to be a reliable fallback for a portfolio demo). The seam in
      `src/agent/llm_provider.py` stays in place (costs nothing to leave), just not filled in.
- [x] ~~Expo/React Native mobile client~~ (was Slice 10) — decided against a
      native app: this is a single-page tool, not something that benefits
      from app-store distribution, and it doubles the UI surface to
      maintain for one extra install step's worth of value. The Next.js
      frontend is already responsive (verified for real in Slice 9e); a
      phone browser is the mobile experience, not a second codebase.
- [x] ~~A standalone data-analysis case study (real EDA/charts over the
      catalog, aimed at a Data Scientist/Data Analyst reviewer)~~ —
      decided against it directly: this project is explicitly targeting
      AI Engineer roles, and the user already has separate DS/DA
      portfolio projects elsewhere covering that audience. Adding one
      here would speak to a reviewer this project isn't for, at the
      cost of time better spent on AI-engineering-specific signal (the
      README hook, quantified results) or on applying/interviewing
      itself. The project's existing domain understanding (schema
      corpus metric notes, eval golden questions, the forecast tool's
      honesty about data maturity) already covers "understands the
      data," which was the only argument for keeping it.
