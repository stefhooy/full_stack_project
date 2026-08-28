"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import GenreIcon from "@/components/GenreIcon";
import { fetchGamesByGenre, fetchGenres, type GenreGame, type Genre } from "@/lib/genres";

const container = {
  hidden: {},
  show: {
    transition: { staggerChildren: 0.05 },
  },
};

const card = {
  hidden: { opacity: 0, y: 22, scale: 0.96 },
  show: { opacity: 1, y: 0, scale: 1, transition: { duration: 0.45, ease: [0.16, 1, 0.3, 1] as const } },
};

function CardSkeleton() {
  return (
    <div className="panel rounded-lg p-4 animate-pulse">
      <div className="h-8 w-8 rounded-md bg-[var(--border-strong)]" />
      <div className="h-3.5 w-16 rounded bg-[var(--border-strong)] mt-3" />
      <div className="h-2.5 w-10 rounded bg-[var(--border-strong)] mt-2" />
    </div>
  );
}

function GamesLeaderboard({
  genre,
  games,
  loading,
  onAsk,
  disabled,
}: {
  genre: Genre;
  games: GenreGame[] | null;
  loading: boolean;
  onAsk: () => void;
  disabled: boolean;
}) {
  return (
    <motion.div
      key={genre.label}
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: "auto" }}
      exit={{ opacity: 0, height: 0 }}
      transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
      className="overflow-hidden"
    >
      <div
        className="panel mt-2.5 rounded-lg px-4 py-3.5"
        style={{ ["--g" as string]: `var(${genre.hueVar})` }}
      >
        <div className="flex items-baseline justify-between mb-2.5 flex-wrap gap-2">
          <span
            className="font-mono text-[11px] uppercase tracking-wide font-medium"
            style={{ color: "var(--g)" }}
          >
            Top {genre.label} games
          </span>
          <button
            type="button"
            onClick={onAsk}
            disabled={disabled}
            className="text-[11px] text-[var(--muted)] hover:text-[var(--foreground)] disabled:opacity-40 transition-colors"
          >
            Ask the agent about {genre.label} →
          </button>
        </div>

        {loading && (
          <div className="space-y-1.5">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="h-5 rounded bg-[var(--border-strong)] animate-pulse" />
            ))}
          </div>
        )}

        {!loading && games && games.length === 0 && (
          <div className="text-sm text-[var(--muted)]">
            No {genre.label} games found in the catalog.
          </div>
        )}

        {!loading && games && games.length > 0 && (
          <ul className="font-mono text-xs sm:text-sm divide-y divide-[var(--border)]">
            {games.map((game, i) => (
              <li key={game.name} className="flex items-center gap-3 py-1.5">
                <span className="text-[var(--muted)] w-5 shrink-0 tabular-nums">
                  {i + 1}
                </span>
                <span className="flex-1 truncate">{game.name}</span>
                <span className="text-[var(--muted)] shrink-0 w-14 text-right tabular-nums">
                  {game.price_usd == null ? "n/a" : game.price_usd === 0 ? "free" : `$${game.price_usd.toFixed(2)}`}
                </span>
                <span className="text-[var(--muted)] shrink-0 w-12 text-right tabular-nums">
                  {game.review_score == null ? "n/a" : `${Math.round(game.review_score * 100)}%`}
                </span>
                <span className="text-[var(--muted)] shrink-0 w-24 text-right hidden sm:inline tabular-nums">
                  {game.peak_ccu == null ? "n/a" : `peak ${game.peak_ccu.toLocaleString()}`}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </motion.div>
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
  const [selected, setSelected] = useState<Genre | null>(null);
  const [games, setGames] = useState<GenreGame[] | null>(null);
  const [gamesLoading, setGamesLoading] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetchGenres(controller.signal)
      .then(setGenres)
      .catch((e) => {
        if ((e as Error).name !== "AbortError") setFailed(true);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!selected) return;
    const controller = new AbortController();
    fetchGamesByGenre(selected.label, 8, controller.signal)
      .then(setGames)
      .catch((e) => {
        if ((e as Error).name !== "AbortError") setSelected(null);
      })
      .finally(() => setGamesLoading(false));
    return () => controller.abort();
  }, [selected]);

  if (failed) return null;

  function toggle(g: Genre) {
    const next = selected?.label === g.label ? null : g;
    setSelected(next);
    setGames(null);
    setGamesLoading(Boolean(next));
  }

  return (
    <section>
      <div className="flex items-baseline justify-between flex-wrap gap-x-3 gap-y-1 mb-3">
        <h2 className="text-sm font-medium text-[var(--foreground)]">Explore by genre</h2>
        <span className="text-xs text-[var(--muted)] whitespace-nowrap">
          {genres ? "Live from the catalog" : "Loading…"}
        </span>
      </div>
      {!genres ? (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
          {Array.from({ length: 8 }).map((_, i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
      ) : (
        <>
          <motion.div
            variants={container}
            initial="hidden"
            whileInView="show"
            viewport={{ once: true, margin: "-40px" }}
            className="grid grid-cols-2 sm:grid-cols-4 gap-2.5"
          >
            {genres.map((g) => {
              const isSelected = selected?.label === g.label;
              return (
                <motion.button
                  key={g.label}
                  variants={card}
                  type="button"
                  onClick={() => toggle(g)}
                  whileHover={{ y: -2 }}
                  whileTap={{ scale: 0.97 }}
                  transition={{ duration: 0.15, ease: "easeOut" }}
                  className="panel rounded-lg p-4 text-left transition-colors duration-150"
                  style={{
                    ["--g" as string]: `var(${g.hueVar})`,
                    borderColor: isSelected ? "var(--g)" : "var(--border)",
                  }}
                >
                  <span
                    className="inline-flex h-8 w-8 items-center justify-center rounded-md"
                    style={{
                      color: "var(--g)",
                      background: "color-mix(in srgb, var(--g) 14%, transparent)",
                    }}
                  >
                    <GenreIcon genreId={g.id} label={g.label} />
                  </span>
                  <div className="text-sm font-medium leading-tight mt-3">{g.label}</div>
                  <div className="text-xs text-[var(--muted)] mt-0.5 tabular-nums">
                    {g.count.toLocaleString()} games
                  </div>
                </motion.button>
              );
            })}
          </motion.div>

          <AnimatePresence mode="wait">
            {selected && (
              <GamesLeaderboard
                genre={selected}
                games={games}
                loading={gamesLoading}
                disabled={disabled}
                onAsk={() => onPick(selected.question)}
              />
            )}
          </AnimatePresence>
        </>
      )}
    </section>
  );
}
