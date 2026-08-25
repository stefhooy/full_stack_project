"use client";

import { useEffect, useState } from "react";
import { motion } from "motion/react";
import GenreIcon from "@/components/GenreIcon";
import { fetchGenres, type Genre } from "@/lib/genres";

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

function CardSkeleton() {
  return (
    <div className="border-2 border-[var(--border)] bg-[var(--surface)] p-3.5 animate-pulse">
      <div className="h-9 w-9 bg-[var(--border)]" />
      <div className="h-3.5 w-16 bg-[var(--border)] mt-3" />
      <div className="h-2.5 w-10 bg-[var(--border)] mt-2" />
    </div>
  );
}

export default function GenreShowcase({
  onPick,
  disabled,
}: {
  onPick: (question: string) => void;
  disabled: boolean;
}) {
  const [genres, setGenres] = useState<Genre[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetchGenres(controller.signal)
      .then(setGenres)
      .catch((e) => {
        if ((e as Error).name !== "AbortError") setFailed(true);
      });
    return () => controller.abort();
  }, []);

  if (failed) return null;

  return (
    <section>
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="font-pixel text-[10px] text-[var(--muted)] tracking-wide">
          [ OR EXPLORE BY GENRE ]
        </h2>
        <span className="text-[11px] font-mono text-[var(--muted)]">
          {genres ? "live from the catalog" : "loading..."}
        </span>
      </div>
      {!genres ? (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
          {Array.from({ length: 8 }).map((_, i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
      ) : (
        <motion.div
          variants={container}
          initial="hidden"
          whileInView="show"
          viewport={{ once: true, margin: "-40px" }}
          className="grid grid-cols-2 sm:grid-cols-4 gap-2.5"
        >
          {genres.map((g) => (
            <motion.button
              key={g.label}
              variants={card}
              type="button"
              disabled={disabled}
              onClick={() => onPick(g.question)}
              whileHover={disabled ? undefined : { y: -3 }}
              whileTap={disabled ? undefined : { scale: 0.97 }}
              className="group relative overflow-hidden border-2 border-[var(--border)] bg-[var(--surface)] p-3.5 text-left disabled:opacity-40 disabled:cursor-not-allowed transition-[border-color,box-shadow] duration-200 hover:border-[var(--g)]"
              style={{
                ["--g" as string]: `var(${g.hueVar})`,
                boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.03)",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.boxShadow =
                  "inset 0 0 0 1px rgba(255,255,255,0.03), 0 0 0 1px var(--g), 0 0 18px color-mix(in srgb, var(--g) 55%, transparent)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.boxShadow = "inset 0 0 0 1px rgba(255,255,255,0.03)";
              }}
            >
              {/* corner brackets, HUD-style, same idea as the trace stepper's LED dots */}
              <span className="pointer-events-none absolute top-0 left-0 h-2.5 w-2.5 border-t-2 border-l-2 border-[var(--g)] opacity-0 group-hover:opacity-100 transition-opacity" />
              <span className="pointer-events-none absolute bottom-0 right-0 h-2.5 w-2.5 border-b-2 border-r-2 border-[var(--g)] opacity-0 group-hover:opacity-100 transition-opacity" />

              <span
                className="relative inline-flex h-9 w-9 items-center justify-center mb-2.5"
                style={{
                  color: "var(--g)",
                  background: "color-mix(in srgb, var(--g) 16%, transparent)",
                  boxShadow: "0 0 0 1px color-mix(in srgb, var(--g) 45%, transparent)",
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
      )}
    </section>
  );
}
