# AI Game Analyst — frontend

The Next.js UI for [AI Game Analyst](../README.md). See the repo root README
for the full project (backend, agent, evals) and PLAN.md/DOCEXP.md for the
roadmap and engineering log. This file covers just this app.

## Dev

```bash
cp .env.local.example .env.local   # points at http://localhost:8000 by default
npm install
npm run dev
```

Requires the backend running (see the root README) — this app calls it
directly via `NEXT_PUBLIC_API_BASE_URL`, no server-side proxy.

## What's here

A restrained dev-tool identity (near-black/off-white, one accent, real
typographic hierarchy) — see DOCEXP.md's Slice 9g entry for why this
replaced an earlier retro-arcade direction wholesale rather than iterating
on it.

- `app/page.tsx` — the whole UI: hero (headline + the 3D scene), ask
  console, example questions, genre picker, streamed progress (as an
  animated trace stepper), answer, chart/table, stats/forecast result.
- `app/globals.css` — one committed dark palette (no light/dark split for
  chrome tokens — a deliberate exception carried over from Slice 9d, see
  DOCEXP.md; this class of dev-tool product routinely ships dark-only
  marketing pages), `--accent` the same warm gold used since
  ARCHITECTURE.md's trace artifact, and the plain hairline-bordered
  `.panel` surface every card/result panel uses (no blur/translucency —
  the busy background that justified glass panels is gone).
- `lib/api.ts` — hand-rolled SSE parsing over `fetch` (not `EventSource`,
  which can't send the POST body the question needs) against the backend's
  `/ask/stream` endpoint.
- `lib/genres.ts` — curation metadata (hand-drawn icon id, a nicer example
  question) for the genre picker, keyed by label, plus `fetchGamesByGenre()`.
  NOT the genre list itself — that's fetched live from `GET /genres` at
  render time (`fetchGenres()`), so counts and which genres appear both
  track the real catalog instead of a snapshot baked into this file. A
  genre outside the curated set gets a generic icon/question instead of
  breaking — see DOCEXP.md's Slice 9b entry.
- `components/Chart.tsx` — bar/scatter rendering via Recharts, styled from
  the validated default palette (single hue — every question produces at
  most one series, so no categorical palette or legend is needed).
- `components/Markdown.tsx` — `react-markdown` + `remark-gfm` wrapped with
  an explicit per-element `components` map styled to this app's tokens, so
  the agent's answer (including real GFM tables) renders properly instead
  of showing literal `**asterisks**` or raw pipes/dashes — see DOCEXP.md's
  Slice 9c/9e entries. The real fix for malformed (non-table-shaped)
  markdown lives on the backend, not here — see `src/agent/prompts.py`'s
  formatting rule.
- `components/GenreIcon.tsx` — 10 hand-authored line-art SVG glyphs + a
  generic fallback (no icon library dependency).
- `components/GenreShowcase.tsx` — flat cards (icon + label + count), not
  a decorative shape (an earlier pass used a Game Boy cartridge silhouette
  — dropped in Slice 9g along with the rest of the retro skin). Fetches
  `GET /genres` on mount (loading skeleton + graceful hide-on-failure);
  clicking a card fetches `GET /games` for that genre (deterministic, no
  LLM call) and shows a leaderboard of the real games in it, with a
  secondary link that still bridges into asking the agent about that genre
  through `/ask/stream`.
- `components/HeroScene.tsx` — the hero's one visual flourish: a React
  Three Fiber (WebGL) canvas with 6 lit 3D primitive objects in the genre
  categorical palette, gentle rotation + mouse-parallax, `prefers-reduced-
  motion`-aware. Real 3D, not CSS `transform: rotateX/Y` — see DOCEXP.md's
  Slice 9g entry for why that distinction mattered here, and for the
  React-Compiler-lint-rules-vs-R3F friction points it hit (all fixed
  properly, not suppressed).
- `components/TraceSteps.tsx` — turns streamed progress events into a
  node-by-node animated trace (router → schema → think → query → chart),
  the same visual language as the root `ARCHITECTURE.md` agent-trace
  diagram/artifact, instead of a flat text log. `forecast`-routed questions
  flow through this exact same trace (forecast isn't a separate terminal
  node — see DOCEXP.md's Slice 9b entry).
- `components/MotionProvider.tsx` — wraps the app in `MotionConfig
  reducedMotion="user"` so every animation in the tree honors
  `prefers-reduced-motion` automatically.
- Animation: [Motion](https://motion.dev) for every state-driven UI
  transition (hero entrance, card hover, `AnimatePresence`, the blur
  transitions between panels). React Three Fiber's own render loop
  (`useFrame`) drives the hero scene — Anime.js, used for an earlier
  version of the background, no longer has a job and was removed.
- Type: [Geist](https://vercel.com/font) (UI/body/headline — real
  typographic hierarchy carries the hero instead of a display face) + IBM
  Plex Mono (data/code, same face ARCHITECTURE.md's trace artifact uses).

## Deploy

See the root README's "Deploying" section — this app deploys to Vercel
with `frontend` set as the project's root directory.
