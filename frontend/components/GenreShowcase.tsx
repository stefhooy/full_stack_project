"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import GenreCartridge from "@/components/GenreCartridge";
import { fetchGamesByGenre, fetchGenres, type GenreGame, type Genre } from "@/lib/genres";

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
    <div className="glass-panel aspect-[3/4] border-2 border-[var(--border)] p-3.5 animate-pulse">
      <div className="h-9 w-9 bg-[var(--border)] mx-auto mt-4" />
      <div className="h-3.5 w-16 bg-[var(--border)] mt-4 mx-auto" />
      <div className="h-2.5 w-10 bg-[var(--border)] mt-2 mx-auto" />
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
        className="glass-panel mt-2.5 border-2 px-4 py-3.5"
        style={{ ["--g" as string]: `var(${genre.hueVar})`, borderColor: "var(--border)" }}
      >
        <div className="flex items-baseline justify-between mb-2.5 flex-wrap gap-2">
          <span className="font-pixel text-[8px] tracking-wide" style={{ color: "var(--g)" }}>
            [ TOP {genre.label.toUpperCase()} GAMES ]
          </span>
          <button
            type="button"
            onClick={onAsk}
            disabled={disabled}
            className="text-[11px] font-mono text-[var(--muted)] hover:text-[var(--accent)] disabled:opacity-40 transition-colors"
          >
            ask the agent about {genre.label} →
          </button>
        </div>

        {loading && (
          <div className="space-y-1.5">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="h-5 bg-[var(--border)] animate-pulse" />
            ))}
          </div>
        )}

        {!loading && games && games.length === 0 && (
          <div className="text-sm font-mono text-[var(--muted)]">
            No {genre.label} games found in the catalog.
          </div>
        )}

        {!loading && games && games.length > 0 && (
          <ul className="font-mono text-xs sm:text-sm divide-y divide-[var(--border)]">
            {games.map((game, i) => (
              <li
                key={game.name}
                className="flex items-center gap-3 py-1.5 hover:bg-[color-mix(in_srgb,var(--g)_8%,transparent)] transition-colors"
              >
                <span className="font-pixel text-[8px] w-6 shrink-0" style={{ color: "var(--g)" }}>
                  {String(i + 1).padStart(2, "0")}
                </span>
                <span className="flex-1 truncate">{game.name}</span>
                <span className="text-[var(--muted)] shrink-0 w-14 text-right">
                  {game.price_usd == null ? "—" : game.price_usd === 0 ? "free" : `$${game.price_usd.toFixed(2)}`}
                </span>
                <span className="text-[var(--muted)] shrink-0 w-12 text-right">
                  {game.review_score == null ? "—" : `${Math.round(game.review_score * 100)}%`}
                </span>
                <span className="text-[var(--muted)] shrink-0 w-20 text-right hidden sm:inline">
                  {game.peak_ccu == null ? "—" : `peak ${game.peak_ccu.toLocaleString()}`}
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
        <h2 className="font-pixel text-[10px] text-[var(--muted)] tracking-wide">
          [ OR EXPLORE BY GENRE ]
        </h2>
        <span className="text-[11px] font-mono text-[var(--muted)] whitespace-nowrap">
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
        <>
          <motion.div
            variants={container}
            initial="hidden"
            whileInView="show"
            viewport={{ once: true, margin: "-40px" }}
            className="grid grid-cols-2 sm:grid-cols-4 gap-2.5"
          >
            {genres.map((g) => (
              <motion.div key={g.label} variants={card}>
                <GenreCartridge
                  genre={g}
                  selected={selected?.label === g.label}
                  onClick={() => toggle(g)}
                />
              </motion.div>
            ))}
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
