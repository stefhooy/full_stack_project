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

Slice 18, adding a cartridge detail popup to Slice 17's film strip on
real positive feedback for the first time in this project's redesign
history. See DOCEXP.md for the full history
(Slice 9g's near-black dev-tool look, Slice 12b's turquoise pass, Slice
13's light "Roman Intelligence" re-skin, Slice 14/14b/14c's dark
illustrated-then-photographic Roman statue, Slice 15's monochrome-plus-
live-data-scatter restart, Slice 16's film-strip-plus-bronze-accent
rebuild). Current identity: a dark, green-tinted background, a neon
green `--accent`, Rajdhani (a technical, gaming-adjacent sans) as the
one type face, and two small, specific Latin/Roman touches (the film
strip's frame, the genre icons' medallion ring) rather than reviving the
deleted full Roman identity.

- `app/page.tsx` — the whole UI: hero (headline + `HeroPreview`, a real
  verified answer shown in a floating panel), ask console, example
  questions, the "Meet Ludo" capabilities section, genre picker, streamed
  progress (as an animated trace stepper), answer, chart/table,
  stats/forecast result.
- `app/catalog/` — the full-catalog browse page (search/filter/sort/
  paginate over all 1,000 games, `GET /catalog`, no LLM call). `page.tsx`
  is a thin server wrapper (for a real per-route `<title>`) around the
  actual `"use client"` component, `CatalogClient.tsx`.
- `app/globals.css` — one committed dark palette (no light/dark split for
  chrome tokens — a deliberate exception carried over from Slice 9d, see
  DOCEXP.md; this class of product routinely ships one committed marketing
  theme). `--accent` is neon green as of Slice 17 (deliberately picked
  brighter/more saturated than genre slot 6's own muted green, so the two
  don't read as a coincidental collision). The genre categorical palette
  was re-picked and run through the dataviz skill's validator against
  this app's own dark-green background — the reference default and an
  earlier earth-tone draft both failed the adjacent-CVD-separation check;
  the passing set spreads across the full hue wheel instead (see
  DOCEXP.md's Slice 16 entry for why hue clustering can't pass no matter
  the order). Also defines `.filmstrip-track`, the film strip's native
  CSS keyframe slide (see below for why it's plain CSS, not Motion). The
  `.panel` flat hairline-bordered dark surface every card/result panel
  uses is unchanged.
- `components/FilmStrip.tsx` — the hero's visual: real cover art for real
  games, hotlinked from Steam's own CDN (`library_600x900.jpg`, the same
  asset each game's store page uses — verified reachable with a live curl
  before wiring this up), sliding in a full-bleed infinite loop inside a
  frame with real film sprocket holes (a tiled `repeating radial-
  gradient`, not extra DOM elements) and a double-rule accent border.
  The slide is a native CSS keyframe animation (`.filmstrip-track`) so
  hovering can pause it with `animation-play-state` and resume exactly
  in place — a Motion-driven keyframe tween stopped and restarted the
  same way risks a visible jump (see DOCEXP.md's Slice 17 entry, verified
  programmatically, not just visually). Each cover also gets an
  independent Motion `whileHover` (scale + accent glow) layered on top.
  Needs `appid` on `CatalogGame` (added to `src/db/catalog.py`'s columns)
  and a `remotePatterns` entry in `next.config.ts` for Steam's CDN, the
  one remote-image source in this app. A cover that fails to load drops
  out of the strip via `onError` rather than showing broken. Clicking a
  cover opens `GameCartridge.tsx`, a cartridge-shaped detail card for
  that one game (cover, name, genre, release date, Metacritic,
  platforms, price, review score, owners, peak players, all from the
  same `CatalogGame` object the strip already fetched, no second
  request), closable via its X button, a backdrop click, or Escape.
  Deliberately not a `layoutId` shared-layout morph from the clicked
  cover, since the strip's own list is duplicated for its seamless loop
  (`[...visible, ...visible]`), so two DOM nodes share the same `appid`
  at once and a shared-layout id would be ambiguous about its source
  (see DOCEXP.md's Slice 18 entry) — it's a plain `AnimatePresence`
  scale-and-fade pop instead. The slide pauses deterministically while
  a cartridge is open (an inline `animationPlayState`, alongside the
  existing `:hover` CSS rule) and resumes the instant it closes.
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
  generic fallback (no icon library dependency), redrawn in Slice 16 with
  a thin engraved-medallion ring built into every glyph itself (a coin/
  seal touch, the second small Latin/Roman accent this slice added).
- `components/GenreShowcase.tsx` — flat cards (icon + label + count).
  Fetches `GET /genres` on mount (loading skeleton + graceful
  hide-on-failure); clicking a card fetches `GET /games` for that genre
  (deterministic, no LLM call) and shows a leaderboard of the real games
  in it, with a secondary link that still bridges into asking the agent
  about that genre through `/ask/stream`.
- `components/HeroPreview.tsx` — a static floating panel below the hero
  showing a real, previously-verified Ludo answer, styled identically to
  the app's actual result panel.
- `components/MeetLudo.tsx` — three real capabilities (Ask / Investigate /
  Show the work, mapped to the actual agent graph in `ARCHITECTURE.md`,
  not a decorative visual) plus example questions exercising the Slice 11
  fields (Metacritic, platforms, release date, categories).
- `components/Nav.tsx` — the shared nav: a plain text wordmark and two
  links, no icon.
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
  transitions between panels, `FilmStrip`'s infinite sliding loop). No
  WebGL/3D, no fixed animated background layer.
- Type: Rajdhani (Slice 17, replacing Geist directly on request for
  "professional but also gamer like" — a technical, esports/gaming-HUD-
  adjacent sans with clean enough weights to still work as body copy)
  at every scale from the hero headline down to a button label, plus IBM
  Plex Mono for data/code (same face ARCHITECTURE.md's trace artifact
  uses). One sans family carrying the whole range, no second display
  face.

## A hard site-wide rule: no em dashes, no en dashes

Set directly by the user, applies to every page. Every hardcoded UI
string is grep-verified dash-free (`grep -rn` for U+2014/U+2013 across
`app/`, `components/`, `lib/` should only ever match code comments, never
rendered strings). The harder part isn't this app's own copy though —
it's the agent's own generated answer text, which a small fast LLM will
drift back to em dashes in even with a system-prompt rule telling it not
to (confirmed for real, not hypothesized). That's fixed on the backend,
not here: see `src/agent/graph.py`'s `_strip_dashes()` and the root
README's note on it. If you add new hardcoded copy to this app, run the
same grep before considering it done.

## Deploy

See the root README's "Deploying" section — this app deploys to Vercel
with `frontend` set as the project's root directory.
