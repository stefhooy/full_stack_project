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
- [ ] Deploy for real: Vercel (frontend) + Render or Fly.io (backend) —
      already the resolved plan since Slice 6 (see README's "Deploying"
      section for the concrete steps); this slice is actually doing it, not
      re-deciding it. User's to execute (account creation, secrets) per
      their standing preference to handle external/billing-adjacent actions
      themselves

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
- [ ] `poll_player_counts.yml`'s catalog-rebuild step now costs ~2.5x more
      CI time per scheduled run (the new per-game storefront calls, no
      persisted `data/raw/` cache between GH Actions runs) for data that
      step doesn't actually need — it only wants appids. Flagged, not yet
      addressed; a narrower "appids-only" ingestion path is the likely fix
      if this becomes a real problem
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
