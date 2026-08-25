"use client";

import { motion } from "motion/react";
import GenreIcon from "@/components/GenreIcon";
import type { Genre } from "@/lib/genres";

// A Game Boy-style cartridge, not a card: the same chamfered-corner
// silhouette as a real GB/GBC cart, a "label sticker" window for the genre
// icon/name, and a ridge of connector notches at the bottom edge. One
// shape family for all 8 genres (not alternating GB/DS shapes) for visual
// cohesion — see DOCEXP.md for why.
//
// The shape is drawn twice, deliberately: `clip-path` on the glass-panel
// div actually cuts the corner (so the frosted-blur body is really
// pentagon-shaped, not just a rectangle with a triangle painted over it),
// and a separate stroke-only SVG polygon on top draws the visible outline
// — including along the diagonal, which `clip-path` alone never draws a
// border on (it just removes pixels; nothing paints the new edge it
// creates). Without the SVG overlay the chamfer is real but invisible.
const CHAMFER_X = 0.22;
const CHAMFER_Y = 0.16;
const CARTRIDGE_CLIP = `polygon(${CHAMFER_X * 100}% 0%, 100% 0%, 100% 100%, 0% 100%, 0% ${CHAMFER_Y * 100}%)`;
const OUTLINE_POINTS = `${120 * CHAMFER_X},0 120,0 120,160 0,160 0,${160 * CHAMFER_Y}`;

export default function GenreCartridge({
  genre,
  selected,
  onClick,
}: {
  genre: Genre;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <motion.button
      type="button"
      onClick={onClick}
      whileHover={{ y: -10, rotate: -1.5 }}
      whileTap={{ y: -2, scale: 0.98 }}
      transition={{ type: "spring", stiffness: 340, damping: 20 }}
      className="group relative aspect-[3/4] w-full text-left"
      style={{ ["--g" as string]: `var(${genre.hueVar})` }}
    >
      <div
        className="glass-panel absolute inset-0 flex flex-col"
        style={{ clipPath: CARTRIDGE_CLIP }}
      >
        {/* shell seam */}
        <div
          className="absolute left-0 right-0 h-px opacity-40"
          style={{ top: "22%", background: "var(--border)" }}
        />

        {/* label sticker */}
        <div
          className="mx-3 flex flex-1 flex-col items-center justify-center gap-2 border mt-[26%] mb-4 px-2 py-3"
          style={{
            borderColor: "color-mix(in srgb, var(--g) 45%, transparent)",
            background: "color-mix(in srgb, var(--g) 14%, transparent)",
          }}
        >
          <span
            className="inline-flex h-9 w-9 shrink-0 items-center justify-center"
            style={{
              color: "var(--g)",
              background: "color-mix(in srgb, var(--g) 20%, transparent)",
              boxShadow: "0 0 0 1px color-mix(in srgb, var(--g) 55%, transparent)",
            }}
          >
            <GenreIcon genreId={genre.id} label={genre.label} />
          </span>
          <div className="text-center">
            <div className="text-xs sm:text-sm font-semibold leading-tight">{genre.label}</div>
            <div className="text-[10px] font-mono text-[var(--muted)] mt-0.5">
              {genre.count} games
            </div>
          </div>
        </div>

        {/* connector ridge */}
        <div className="flex justify-center gap-1 pb-2.5">
          {Array.from({ length: 5 }).map((_, i) => (
            <span
              key={i}
              className="h-1.5 w-2.5"
              style={{ background: "color-mix(in srgb, var(--foreground) 22%, transparent)" }}
            />
          ))}
        </div>
      </div>

      {/* the visible outline — see the note above for why this can't just
          be a CSS border on the clipped div */}
      <svg
        className="pointer-events-none absolute inset-0 h-full w-full"
        viewBox="0 0 120 160"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <polygon
          points={OUTLINE_POINTS}
          fill="none"
          stroke={selected ? "var(--g)" : "var(--border)"}
          strokeWidth={selected ? 3 : 2}
          strokeLinejoin="round"
          style={{
            filter: selected
              ? "drop-shadow(0 0 6px var(--g))"
              : "none",
            transition: "stroke 0.2s, filter 0.2s",
          }}
        />
      </svg>
    </motion.button>
  );
}
