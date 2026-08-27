"use client";

import { motion } from "motion/react";

// The hero's product visual — a static preview of a real, previously-run
// Ludo answer (the five numbers below are genuine output from the actual
// backend against the real catalog, captured during Slice 13 development,
// not invented for this panel), styled as the same floating white card the
// rest of the app's result panel already uses. Replaces the earlier
// abstract-3D-shapes hero visual: those don't fit this re-skin's elegant,
// restrained marble-and-serif world the way a saturated genre-colored
// icosahedron cluster did the old dark dev-tool identity. This is closer
// to what a premium AI product's hero visual actually is anyway — a real
// glimpse of the product, not a decorative illustration next to it.
const GAMES = [
  { name: "Aseprite", score: "0.991", reviews: "21,620" },
  { name: "HoloCure – Save the Fans!", score: "0.990", reviews: "37,623" },
  { name: "Portal 2", score: "0.987", reviews: "427,835" },
  { name: "The Henry Stickmin Collection", score: "0.987", reviews: "50,017" },
];

export default function HeroPreview() {
  return (
    <motion.div
      initial={{ opacity: 0, y: 16, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1], delay: 0.15 }}
      className="panel rounded-xl p-5 w-full max-w-md mx-auto"
    >
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <span
            className="inline-flex h-6 w-6 items-center justify-center rounded-full text-[10px] font-semibold"
            style={{ background: "var(--accent)", color: "var(--accent-contrast)" }}
          >
            L
          </span>
          <span className="text-sm font-medium">Ludo</span>
        </div>
        <span
          className="inline-flex items-center rounded-full px-2.5 py-0.5 text-[11px] font-medium"
          style={{ color: "var(--accent)", background: "color-mix(in srgb, var(--accent) 10%, transparent)" }}
        >
          Lookup
        </span>
      </div>

      <p className="text-sm text-[var(--muted)] mb-1">Question</p>
      <p className="text-sm mb-4">
        &ldquo;What are the highest-rated games with more than 1000 positive reviews?&rdquo;
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
        Real answer from the actual 1,000-game catalog — not a mockup.
      </div>
    </motion.div>
  );
}
