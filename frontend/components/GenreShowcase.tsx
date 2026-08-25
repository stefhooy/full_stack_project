"use client";

import { motion } from "motion/react";
import GenreIcon from "@/components/GenreIcon";
import { GENRES } from "@/lib/genres";

const container = {
  hidden: {},
  show: {
    transition: { staggerChildren: 0.06 },
  },
};

const card = {
  hidden: { opacity: 0, y: 14 },
  show: { opacity: 1, y: 0, transition: { duration: 0.4, ease: [0.16, 1, 0.3, 1] as const } },
};

export default function GenreShowcase({
  onPick,
  disabled,
}: {
  onPick: (question: string) => void;
  disabled: boolean;
}) {
  return (
    <section>
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="text-xs font-mono uppercase tracking-[0.14em] text-[var(--muted)]">
          Or explore by genre
        </h2>
        <span className="text-[11px] font-mono text-[var(--muted)]">
          real counts, 200-game catalog
        </span>
      </div>
      <motion.div
        variants={container}
        initial="hidden"
        whileInView="show"
        viewport={{ once: true, margin: "-40px" }}
        className="grid grid-cols-2 sm:grid-cols-4 gap-2.5"
      >
        {GENRES.map((g) => (
          <motion.button
            key={g.id}
            variants={card}
            type="button"
            disabled={disabled}
            onClick={() => onPick(g.question)}
            whileHover={disabled ? undefined : { y: -3 }}
            whileTap={disabled ? undefined : { scale: 0.97 }}
            className="group relative overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface)] p-3.5 text-left disabled:opacity-40 disabled:cursor-not-allowed transition-shadow"
            style={{ ["--g" as string]: `var(${g.hueVar})` }}
          >
            <span
              className="pointer-events-none absolute -inset-px opacity-0 group-hover:opacity-100 transition-opacity duration-300"
              style={{
                background:
                  "radial-gradient(120px 80px at 20% 0%, color-mix(in srgb, var(--g) 22%, transparent), transparent 70%)",
              }}
            />
            <span
              className="relative inline-flex h-8 w-8 items-center justify-center rounded-lg mb-2.5"
              style={{
                color: "var(--g)",
                background: "color-mix(in srgb, var(--g) 14%, transparent)",
              }}
            >
              <GenreIcon genreId={g.id} label={g.label} />
            </span>
            <div className="relative text-sm font-semibold leading-tight">{g.label}</div>
            <div className="relative text-[11px] font-mono text-[var(--muted)] mt-0.5">
              {g.count} games
            </div>
          </motion.button>
        ))}
      </motion.div>
    </section>
  );
}
