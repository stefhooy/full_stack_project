"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import { motion } from "motion/react";
import { fetchCatalog, type CatalogGame } from "@/lib/catalog";
import { useReducedMotion } from "@/lib/useReducedMotion";

// The hero's visual (Slice 16, replacing Slice 15's live data scatter,
// which didn't land): real cover art for real games in the catalog,
// hotlinked from Steam's own CDN (the same asset each game's own store
// page uses -- verified live before wiring this up), sliding past inside
// a frame styled like a real film strip. The one remote-image source in
// this app; everything else is hand-authored code or a locally committed
// asset. A game whose cover fails to load is dropped from the strip
// rather than shown broken (onError removes it from state).
const FRAME_WIDTH = 130;
const FRAME_HEIGHT = 195; // 2:3, matching Steam's library_600x900 cover art
const GAP = 14;

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
  const reduceMotion = useReducedMotion();

  useEffect(() => {
    const controller = new AbortController();
    fetchCatalog({ sort: "peak_ccu", order: "desc", pageSize: 40 }, controller.signal)
      .then((data) => setGames(data.games))
      .catch(() => setGames([]));
    return () => controller.abort();
  }, []);

  const visible = (games ?? []).filter((g) => !broken.has(g.appid));
  // Duplicated once so a -50% translateX loop is seamless -- the second
  // copy lands exactly where the first one started.
  const strip = [...visible, ...visible];
  const frameStep = FRAME_WIDTH + GAP;
  const loopDistance = visible.length * frameStep;

  return (
    <div
      className="relative w-full overflow-hidden"
      style={{ border: "3px double var(--accent)" }}
    >
      <Sprockets />
      <div className="overflow-hidden py-3" style={{ backgroundColor: "var(--accent-contrast)" }}>
        {visible.length > 0 && (
          <motion.div
            className="flex"
            style={{ gap: GAP, paddingInline: GAP }}
            animate={reduceMotion ? undefined : { x: [0, -loopDistance] }}
            transition={{ duration: visible.length * 2.2, repeat: Infinity, ease: "linear" }}
          >
            {strip.map((g, i) => (
              <div
                key={`${g.appid}-${i}`}
                className="relative shrink-0 rounded-sm overflow-hidden"
                style={{ width: FRAME_WIDTH, height: FRAME_HEIGHT }}
                title={g.name}
              >
                <Image
                  src={coverUrl(g.appid)}
                  alt={g.name}
                  fill
                  sizes={`${FRAME_WIDTH}px`}
                  className="object-cover"
                  onError={() => setBroken((prev) => new Set(prev).add(g.appid))}
                />
              </div>
            ))}
          </motion.div>
        )}
        {visible.length === 0 && (
          <div className="h-[195px] flex items-center justify-center text-xs font-mono text-[var(--muted)]">
            loading the real catalog…
          </div>
        )}
      </div>
      <Sprockets />
    </div>
  );
}
