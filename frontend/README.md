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

- `app/page.tsx` — the whole UI: hero, HUD-styled ask console, example
  questions, genre showcase, streamed progress (as an animated trace
  stepper), answer, chart/table, stats/forecast result.
- `app/globals.css` — the 80s-arcade-cabinet design tokens: grounds/accent
  aligned to the root `ARCHITECTURE.md` agent-trace artifact's exact
  palette, the genre categorical palette, and the marquee chase-light
  border / blinking-cursor / CRT-scanline effects (all
  `prefers-reduced-motion`-guarded where animated).
- `lib/api.ts` — hand-rolled SSE parsing over `fetch` (not `EventSource`,
  which can't send the POST body the question needs) against the backend's
  `/ask/stream` endpoint.
- `lib/genres.ts` — curation metadata (hand-drawn icon id, a nicer example
  question) for the genre showcase, keyed by label, plus `fetchGamesByGenre()`.
  NOT the genre list itself — that's fetched live from `GET /genres` at
  render time (`fetchGenres()`), so counts and which genres appear both
  track the real catalog instead of a snapshot baked into this file. A
  genre outside the curated set gets a generic icon/question instead of
  breaking — see DOCEXP.md's Slice 9b entry.
- `components/Chart.tsx` — bar/scatter rendering via Recharts, styled from
  the validated default palette (single hue — every question produces at
  most one series, so no categorical palette or legend is needed).
- `components/Markdown.tsx` — `react-markdown` wrapped with an explicit
  per-element `components` map styled to this app's tokens, so the agent's
  answer (real bold/list markdown) renders properly instead of showing
  literal `**asterisks**` — see DOCEXP.md's Slice 9c entry.
- `components/GenreIcon.tsx` — 10 hand-authored line-art SVG glyphs + a
  generic fallback (no icon library dependency).
- `components/GenreShowcase.tsx` — fetches `GET /genres` on mount (loading
  skeleton + graceful hide-on-failure); clicking a card fetches `GET /games`
  for that genre (deterministic, no LLM call) and shows a retro
  "leaderboard" of the real games in it, with a secondary link that still
  bridges into asking the agent about that genre through `/ask/stream`.
- `components/TraceSteps.tsx` — turns streamed progress events into a
  node-by-node animated trace (router → schema → think → query → chart),
  the same visual language as the root `ARCHITECTURE.md` agent-trace
  diagram/artifact, instead of a flat text log. `forecast`-routed questions
  flow through this exact same trace now (see DOCEXP.md's Slice 9b entry —
  forecast isn't a separate terminal node anymore).
- `components/MotionProvider.tsx` — wraps the app in `MotionConfig
  reducedMotion="user"` so every animation in the tree honors
  `prefers-reduced-motion` automatically.
- `components/RetroBackground.tsx` — an ambient synthwave grid + drifting
  motes behind the page, animated with **Anime.js**, mounted once in
  `app/layout.tsx`. The one deliberate exception to "Motion is the only
  animation library" — scoped to an imperative loop with no React state
  involved at all, never used anywhere else; see DOCEXP.md's Slice 9c entry
  for why that's not a contradiction of the Slice 9 decision.
- Animation: [Motion](https://motion.dev) for every state-driven UI
  transition (hero entrance, card hover, `AnimatePresence`) + Anime.js for
  the one ambient background loop above — not two libraries doing the same
  job, see DOCEXP.md.
- Type: Archivo (body/UI) + IBM Plex Mono (data/code) + Monoton (the hero
  headline only) + Press Start 2P (short pixel labels only) — four faces,
  each confined to exactly one job; see DOCEXP.md's Slice 9b entry for why.

## Deploy

See the root README's "Deploying" section — this app deploys to Vercel
with `frontend` set as the project's root directory.
