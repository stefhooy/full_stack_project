"use client";

import { motion } from "motion/react";

// A real, previously-verified Ludo answer, shown as a static preview
// styled identically to the app's actual result panel. Not a mockup: the
// five numbers below came from the real backend against the real catalog.
// Monochrome (Slice 15 dropped the site's one accent color entirely), so
// the "Lookup" tag and the ranking numbers read in plain foreground/muted
// tones rather than a colored pill.
const GAMES = [
  { name: "Aseprite", score: "0.991" },
  { name: "HoloCure - Save the Fans!", score: "0.990" },
  { name: "Portal 2", score: "0.987" },
  { name: "The Henry Stickmin Collection", score: "0.987" },
];

export default function HeroPreview() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1], delay: 0.15 }}
      className="panel rounded-xl p-5 w-full max-w-md mx-auto"
    >
      <div className="flex items-center justify-between mb-4">
        <span className="text-sm font-medium">Ludo</span>
        <span className="text-[11px] font-mono uppercase tracking-wide text-[var(--muted)] border border-[var(--border)] rounded-full px-2.5 py-0.5">
          Lookup
        </span>
      </div>

      <p className="text-sm text-[var(--muted)] mb-1">Question</p>
      <p className="text-sm mb-4">
        &ldquo;What are the highest rated games with more than 1000 positive reviews?&rdquo;
      </p>

      <p className="text-sm text-[var(--muted)] mb-2">Answer</p>
      <ul className="space-y-1.5">
        {GAMES.map((g, i) => (
          <li key={g.name} className="flex items-center justify-between text-sm">
            <span className="flex items-center gap-2 min-w-0">
              <span className="text-[var(--muted)] text-xs tabular-nums w-3 shrink-0">{i + 1}</span>
              <span className="truncate font-medium">{g.name}</span>
            </span>
            <span className="text-[var(--muted)] font-mono text-xs shrink-0 pl-2 tabular-nums">
              {g.score}
            </span>
          </li>
        ))}
      </ul>

      <div className="mt-4 pt-3 border-t border-[var(--border)] text-[11px] text-[var(--muted)]">
        Real answer from the actual 1,000 game catalog. Not a mockup.
      </div>
    </motion.div>
  );
}
