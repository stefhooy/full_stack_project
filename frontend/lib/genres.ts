// Genre identity used by components/GenreShowcase.tsx. Counts and which
// genres even appear are fetched live from GET /genres (src/db/genre_stats.py
// on the backend) at render time — not a snapshot baked into this file.
// That backend endpoint does the real work: splitting SteamSpy's
// comma-joined `genre` field, counting tokens across the live catalog,
// excluding the two non-genre tags it also carries ("Early Access" is a
// release status, "Free To Play" a pricing model), and capping at 8 per the
// dataviz skill's categorical-palette rule (a 9th series never gets a
// generated hue).
//
// What stays client-side, deliberately, is only what can't be derived from
// the DB: which hand-drawn icon a label gets, and a nicer curated example
// question for the genres common enough to be worth writing one for. Both
// degrade gracefully for a genre outside this curated set (which can happen
// — the catalog's real top-8 can shift as it grows) via GenreIcon's Generic
// fallback glyph and a templated question below.
import { API_BASE_URL } from "@/lib/api";

export interface Genre {
  id: string;
  label: string;
  count: number;
  hueVar: string;
  question: string;
}

const ICON_BY_LABEL: Record<string, string> = {
  action: "action",
  adventure: "adventure",
  indie: "indie",
  rpg: "rpg",
  simulation: "simulation",
  "massively multiplayer": "mmo",
  strategy: "strategy",
  casual: "casual",
  sports: "sports",
  racing: "racing",
};

const CURATED_QUESTIONS: Record<string, string> = {
  action: "What are the 5 highest-rated Action games?",
  adventure: "What's the average price of Adventure games?",
  indie: "Is the price difference between Indie games and other games statistically significant?",
  rpg: "Which RPG has the highest peak concurrent player count?",
  simulation: "Are there any Simulation games with an unusually high review count compared to the rest?",
  "massively multiplayer": "What are the 5 most-owned Massively Multiplayer games?",
  strategy: "How does average playtime compare between Strategy games and Action games?",
  casual: "What are the 5 cheapest well-reviewed Casual games?",
  sports: "What are the 5 highest-rated Sports games?",
  racing: "What's the average price of Racing games?",
};

function idFor(label: string): string {
  return ICON_BY_LABEL[label.toLowerCase()] ?? "generic";
}

function questionFor(label: string): string {
  return (
    CURATED_QUESTIONS[label.toLowerCase()] ??
    `What are the 5 highest-rated ${label} games?`
  );
}

export async function fetchGenres(signal?: AbortSignal): Promise<Genre[]> {
  const response = await fetch(`${API_BASE_URL}/genres`, { signal });
  if (!response.ok) throw new Error(`genres request failed (${response.status})`);
  const data: { genres: { label: string; count: number }[] } = await response.json();
  return data.genres.map((g, i) => ({
    id: idFor(g.label),
    label: g.label,
    count: g.count,
    hueVar: `--genre-${i + 1}`,
    question: questionFor(g.label),
  }));
}
