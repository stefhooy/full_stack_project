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

"Roman Intelligence" (Slice 13): a light, warm-ivory premium-SaaS identity
with a restrained classical accent — see DOCEXP.md's Slice 13 entry for
why this replaced the near-black dev-tool identity (Slice 9g) and the
turquoise-on-black pass that briefly followed it (Slice 12b). The Roman
motifs are two small hand-drawn SVGs (a laurel sprig, one faint line-drawn
arch), never photographic imagery — consistent with this app's standing
no-external-asset discipline.

- `app/page.tsx` — the whole UI: hero (headline + `HeroPreview`, a real
  verified answer shown in a floating panel), ask console, example
  questions, the "Meet Ludo" capabilities section, genre picker, streamed
  progress (as an animated trace stepper), answer, chart/table,
  stats/forecast result.
- `app/catalog/` — the full-catalog browse page (search/filter/sort/
  paginate over all 1,000 games, `GET /catalog`, no LLM call). `page.tsx`
  is a thin server wrapper (for a real per-route `<title>`) around the
  actual `"use client"` component, `CatalogClient.tsx`.
- `app/globals.css` — one committed light palette (no light/dark split for
  chrome tokens — a deliberate exception carried over from Slice 9d, see
  DOCEXP.md; this class of product routinely ships one committed marketing
  theme), `--accent` a royal blue, and the `.panel` floating-card surface
  (white, thin warm-stone border, soft two-layer shadow) every card/result
  panel uses.
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
- `lib/catalog.ts` — `fetchCatalog()` for the `/catalog` page: search,
  genre filter, sort, and pagination against `GET /catalog`
  (`src/db/catalog.py`), no LLM call.
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
- `components/HeroPreview.tsx` — the hero's product visual: a static
  floating panel showing a real, previously-verified Ludo answer, styled
  identically to the app's actual result panel. Replaced an earlier React
  Three Fiber 3D scene (Slice 9g, retired in Slice 13) once the visual
  identity moved from dark/saturated to light/restrained and the shapes
  stopped fitting — see DOCEXP.md's Slice 13 entry.
- `components/MeetLudo.tsx` — three real capabilities (Ask / Investigate /
  Show the work, mapped to the actual agent graph in `ARCHITECTURE.md`,
  not a decorative visual) plus example questions exercising the Slice 11
  fields (Metacritic, platforms, release date, categories).
- `components/Nav.tsx`, `components/icons/{Laurel,Medallion}.tsx`,
  `components/RomanArch.tsx` — the shared nav and this re-skin's two
  hand-drawn Roman motifs (a mirrored laurel-sprig pair flanking the hero
  eyebrow / dividing sections, one faint line-drawn arch in the hero
  background, an abstract ring-and-ticks medallion as the nav logomark).
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
  transitions between panels). No WebGL/3D in this app as of Slice 13 —
  React Three Fiber (Slice 9g's hero scene) was removed once the visual
  identity moved to the light re-skin; the previous entries in this file's
  history cover why it existed and what replaced it.
- Type: Instrument Serif (display headlines only — the one Slice 13
  addition) + [Geist](https://vercel.com/font) (UI/body — real typographic
  hierarchy carries everything that isn't a headline) + IBM Plex Mono
  (data/code, same face ARCHITECTURE.md's trace artifact uses).

## Deploy

See the root README's "Deploying" section — this app deploys to Vercel
with `frontend` set as the project's root directory.
