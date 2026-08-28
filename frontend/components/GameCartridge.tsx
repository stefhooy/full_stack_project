"use client";

import Image from "next/image";
import { AnimatePresence, motion } from "motion/react";
import type { CatalogGame } from "@/lib/catalog";
import { formatDate, formatOwners, formatPlatforms, formatPrice } from "@/lib/formatGame";

// The film strip's detail view: clicking a cover pops this up, styled as
// a cartridge (a rounded body, a narrow ridged "connector" bar along the
// bottom) rather than a plain modal -- a nod to the physical object, not
// a return to this project's earlier, since-deleted retro/pixel skin
// (Slice 9g dropped a literal Game Boy cartridge silhouette for reading
// as too arcade-template; this one stays in the current dark/neon system,
// just shaped like a cartridge). Every field shown is already on the
// CatalogGame the film strip fetched -- no second network call.

function coverUrl(appid: number): string {
  return `https://cdn.cloudflare.steamstatic.com/steam/apps/${appid}/library_600x900.jpg`;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-[var(--muted)]">{label}</div>
      <div className="text-sm font-medium tabular-nums">{value}</div>
    </div>
  );
}

export default function GameCartridge({
  game,
  onClose,
}: {
  game: CatalogGame | null;
  onClose: () => void;
}) {
  return (
    <AnimatePresence>
      {game && (
        <motion.div
          className="fixed inset-0 z-[100] flex items-center justify-center p-6"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
        >
          <motion.div
            className="absolute inset-0"
            style={{ background: "rgba(4, 6, 5, 0.8)" }}
            onClick={onClose}
            aria-hidden="true"
          />
          <motion.div
            role="dialog"
            aria-modal="true"
            aria-label={game.name}
            className="relative w-full max-w-sm overflow-hidden rounded-2xl"
            style={{ background: "var(--surface-raised)", border: "1px solid var(--border-strong)" }}
            initial={{ opacity: 0, scale: 0.85, y: 24 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.85, y: 24 }}
            transition={{ duration: 0.3, ease: [0.16, 1, 0.3, 1] }}
          >
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="absolute right-3 top-3 z-10 flex h-8 w-8 items-center justify-center rounded-full text-lg"
              style={{ background: "var(--accent-contrast)", color: "var(--accent)" }}
            >
              &times;
            </button>

            <div className="relative w-full" style={{ aspectRatio: "600 / 300" }}>
              <Image src={coverUrl(game.appid)} alt={game.name} fill className="object-cover" />
              <div
                className="absolute inset-0"
                style={{ background: "linear-gradient(to top, var(--surface-raised), transparent 60%)" }}
              />
            </div>

            <div className="px-5 pb-5 -mt-6 relative">
              <h2 className="text-lg font-semibold mb-1 text-balance">{game.name}</h2>
              <p className="text-xs text-[var(--muted)] mb-4">{game.genre ?? "n/a"}</p>

              <div className="grid grid-cols-2 gap-3 mb-5">
                <Stat label="Released" value={formatDate(game.release_date)} />
                <Stat label="Metacritic" value={game.metacritic_score?.toString() ?? "n/a"} />
                <Stat label="Platforms" value={formatPlatforms(game.platforms)} />
                <Stat label="Price" value={formatPrice(game.price_usd)} />
                <Stat
                  label="Score"
                  value={game.review_score == null ? "n/a" : `${Math.round(game.review_score * 100)}%`}
                />
                <Stat label="Owners" value={formatOwners(game.owners_low, game.owners_high)} />
                <Stat
                  label="Peak players"
                  value={game.peak_ccu == null ? "n/a" : game.peak_ccu.toLocaleString()}
                />
              </div>
            </div>

            {/* the connector: a ridged bar along the bottom edge, the one
                detail that reads as "cartridge" rather than "plain card" */}
            <div
              className="h-4 w-full flex items-center gap-[3px] px-5"
              style={{ background: "var(--accent-contrast)" }}
              aria-hidden="true"
            >
              {Array.from({ length: 14 }).map((_, i) => (
                <div key={i} className="h-2 flex-1 rounded-[1px]" style={{ background: "var(--border-strong)" }} />
              ))}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
