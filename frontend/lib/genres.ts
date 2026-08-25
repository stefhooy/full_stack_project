// Genre identity used by components/GenreShowcase.tsx.
//
// `count` is real: SteamSpy's `genre` field is a comma-joined free-text list
// (e.g. "Action, Adventure, RPG"), so this was produced by splitting every
// row in the actual 200-game catalog on comma and counting tokens — not
// guessed. The 8 genres below are the true top 8 by that count; two
// non-genre tags SteamSpy also emits (release-status "Early Access" and the
// pricing model "Free To Play") were excluded on purpose, and a long tail of
// one-off non-game software categories ("Photo Editing", "Utilities" — noise
// from a handful of mislabeled catalog entries) folds into "Other" rather
// than getting its own slot, per the dataviz skill's categorical-palette
// rule: an 8-hue palette is a hard cap, not a suggestion — a 9th series
// never gets a generated hue.
//
// `hueVar` points at the matching --genre-N custom property in globals.css.
// The mapping is ordered by this real prevalence (most common first) and
// that same order is what's on screen (GenreShowcase renders this array
// in order) — that's what keeps the CVD-safety guarantee the dataviz skill
// validated for this exact 8-hue sequence: it was validated as an ordered
// sequence, and preserving the order preserves the guarantee.
export interface Genre {
  id: string;
  label: string;
  count: number;
  hueVar: string;
  question: string;
}

export const GENRES: Genre[] = [
  {
    id: "action",
    label: "Action",
    count: 148,
    hueVar: "--genre-1",
    question: "What are the 5 highest-rated Action games?",
  },
  {
    id: "adventure",
    label: "Adventure",
    count: 75,
    hueVar: "--genre-2",
    question: "What's the average price of Adventure games?",
  },
  {
    id: "indie",
    label: "Indie",
    count: 67,
    hueVar: "--genre-3",
    question: "Is the price difference between Indie games and other games statistically significant?",
  },
  {
    id: "rpg",
    label: "RPG",
    count: 50,
    hueVar: "--genre-4",
    question: "Which RPG has the highest peak concurrent player count?",
  },
  {
    id: "simulation",
    label: "Simulation",
    count: 41,
    hueVar: "--genre-5",
    question: "Are there any Simulation games with an unusually high review count compared to the rest?",
  },
  {
    id: "mmo",
    label: "Massively Multiplayer",
    count: 38,
    hueVar: "--genre-6",
    question: "What are the 5 most-owned Massively Multiplayer games?",
  },
  {
    id: "strategy",
    label: "Strategy",
    count: 33,
    hueVar: "--genre-7",
    question: "How does average playtime compare between Strategy games and Action games?",
  },
  {
    id: "casual",
    label: "Casual",
    count: 24,
    hueVar: "--genre-8",
    question: "What are the 5 cheapest well-reviewed Casual games?",
  },
];
