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
  stepper), answer, chart/table, stats result.
- `lib/api.ts` — hand-rolled SSE parsing over `fetch` (not `EventSource`,
  which can't send the POST body the question needs) against the backend's
  `/ask/stream` endpoint.
- `lib/genres.ts` — the 8 genre identities shown in the genre showcase.
  Counts and labels are real (split+counted from the actual catalog's
  comma-joined `genre` field), not guessed — see DOCEXP.md's Slice 9 entry.
- `components/Chart.tsx` — bar/scatter rendering via Recharts, styled from
  the validated default palette (single hue — every question produces at
  most one series, so no categorical palette or legend is needed).
- `components/GenreIcon.tsx` — 8 hand-authored line-art SVG glyphs (no icon
  library dependency).
- `components/GenreShowcase.tsx` — the illustrated per-genre grid; clicking
  a card asks that genre's question through the same `/ask/stream` path as
  the example-question chips.
- `components/TraceSteps.tsx` — turns streamed progress events into a
  node-by-node animated trace (router → schema → think → query → chart),
  the same visual language as the root `ARCHITECTURE.md` agent-trace
  diagram/artifact, instead of a flat text log.
- `components/MotionProvider.tsx` — wraps the app in `MotionConfig
  reducedMotion="user"` so every animation in the tree honors
  `prefers-reduced-motion` automatically.
- Animation: [Motion](https://motion.dev) (the current name for Framer
  Motion — same library, same npm-author lineage). It's the only animation
  library in this app; see DOCEXP.md for why react-spring/Anime.js weren't
  also added.

## Deploy

See the root README's "Deploying" section — this app deploys to Vercel
with `frontend` set as the project's root directory.
