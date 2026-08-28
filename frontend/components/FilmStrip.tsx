"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import { motion } from "motion/react";
import { fetchCatalog, type CatalogGame } from "@/lib/catalog";

// The hero's visual: real cover art for real games in the catalog,
// hotlinked from Steam's own CDN (the same asset each game's own store
// page uses -- verified live before wiring this up), sliding past inside
// a frame styled like a real film strip. The one remote-image source in
// this app; everything else is hand-authored code or a locally committed
// asset. A game whose cover fails to load is dropped from the strip
// rather than shown broken (onError removes it from state).
//
// The slide itself is a plain CSS keyframe animation (see .filmstrip-track
// in globals.css), not a Motion-driven one -- hovering pauses it via
// `animation-play-state`, which freezes and resumes exactly where it left
// off. A Motion keyframe tween stopped and restarted the same way risks a
// visible jump, since restarting re-interpolates toward the same keyframe
// list rather than truly pausing in place.
const FRAME_WIDTH = 150;
const FRAME_HEIGHT = 225; // 2:3, matching Steam's library_600x900 cover art
const GAP = 16;

function coverUrl(appid: number): string {
  return `https://cdn.cloudflare.steamstatic.com/steam/apps/${appid}/library_600x900.jpg`;
}

function Sprockets() {
  return (
    <div
      className="h-3.5 w-full"
      style={{
        backgroundColor: "var(--accent-contrast)",
        backgroundImage:
          "radial-gradient(circle at 10px 7px, var(--background) 5px, transparent 5.5px)",
        backgroundSize: "26px 14px",
        backgroundRepeat: "repeat-x",
      }}
      aria-hidden="true"
    />
  );
}

export default function FilmStrip() {
  const [games, setGames] = useState<CatalogGame[] | null>(null);
  const [broken, setBroken] = useState<Set<number>>(new Set());

  useEffect(() => {
    const controller = new AbortController();
    fetchCatalog({ sort: "peak_ccu", order: "desc", pageSize: 60 }, controller.signal)
      .then((data) => setGames(data.games))
      .catch(() => setGames([]));
    return () => controller.abort();
  }, []);

  const visible = (games ?? []).filter((g) => !broken.has(g.appid));
  // Duplicated once so a -50% translateX loop is seamless -- the second
  // copy lands exactly where the first one started.
  const strip = [...visible, ...visible];

  return (
    <div className="relative w-full overflow-hidden" style={{ border: "3px double var(--accent)" }}>
      <Sprockets />
      <div className="overflow-hidden py-3" style={{ backgroundColor: "var(--accent-contrast)" }}>
        {visible.length > 0 && (
          <div
            className="filmstrip-track flex"
            style={{ gap: GAP, paddingInline: GAP, animationDuration: `${visible.length * 2.2}s` }}
          >
            {strip.map((g, i) => (
              <motion.div
                key={`${g.appid}-${i}`}
                className="relative shrink-0 rounded-sm overflow-hidden"
                style={{ width: FRAME_WIDTH, height: FRAME_HEIGHT }}
                title={g.name}
                whileHover={{ scale: 1.08, boxShadow: "0 0 0 2px var(--accent), 0 0 24px var(--accent-glow)" }}
                transition={{ duration: 0.2, ease: "easeOut" }}
              >
                <Image
                  src={coverUrl(g.appid)}
                  alt={g.name}
                  fill
                  sizes={`${FRAME_WIDTH}px`}
                  className="object-cover"
                  onError={() => setBroken((prev) => new Set(prev).add(g.appid))}
                />
              </motion.div>
            ))}
          </div>
        )}
        {visible.length === 0 && (
          <div className="h-[225px] flex items-center justify-center text-xs font-mono text-[var(--muted)]">
            loading the real catalog…
          </div>
        )}
      </div>
      <Sprockets />
    </div>
  );
}
