"use client";

import { useEffect, useRef } from "react";
import { animate } from "animejs";

// Purely decorative — a synthwave grid horizon drifting toward the viewer,
// plus a handful of slow-drifting pixel motes. This is the one place
// Anime.js is used in the app, deliberately separate from Motion: Motion
// drives declarative React state transitions (hero entrance, card hover,
// AnimatePresence) everywhere else in this app, but an ambient, non-
// interactive background loop with no component state to react to is
// exactly Anime.js's job — an imperative timeline animating plain DOM
// targets, not a React tree. Two libraries, two different jobs, not two
// libraries doing the same job (compare to the "just use Motion" call made
// for react-spring/Anime.js earlier in Slice 9 — that was about redundant
// UI-transition libraries; this isn't redundant with anything else here).
//
// Kept deliberately faint (low opacity, --accent-derived color only) so it
// reads as atmosphere behind the content, not as a competing visual layer —
// "professional and sleek" ruled out anything louder. Respects
// prefers-reduced-motion by never starting the loops at all.

const ROW_HEIGHT = 48;
// Rows span 288..624 (18px past both edges of the 300..600 visible band) so
// translating the whole group by exactly one row-height and looping reads
// as a continuous scroll — there's always another row already in place
// where the last one left off, no visible seam at the wrap.
const ROW_YS = Array.from({ length: 9 }, (_, i) => 288 + i * ROW_HEIGHT);
const MOTE_COUNT = 6;

export default function RetroBackground() {
  const gridRef = useRef<SVGGElement>(null);
  const motesRef = useRef<SVGGElement>(null);

  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce) return;

    const animations: ReturnType<typeof animate>[] = [];

    if (gridRef.current) {
      animations.push(
        animate(gridRef.current, {
          translateY: [0, ROW_HEIGHT],
          duration: 2600,
          loop: true,
          ease: "linear",
        })
      );
    }

    if (motesRef.current) {
      const motes = motesRef.current.querySelectorAll<SVGRectElement>(".retro-mote");
      motes.forEach((mote, i) => {
        animations.push(
          animate(mote, {
            translateY: [0, -14, 0],
            opacity: [0.12, 0.32, 0.12],
            duration: 5200 + i * 620,
            delay: i * 260,
            loop: true,
            ease: "inOutSine",
          })
        );
      });
    }

    return () => {
      animations.forEach((a) => a.pause());
    };
  }, []);

  return (
    <svg
      className="fixed inset-0 -z-10 h-full w-full"
      preserveAspectRatio="xMidYMax slice"
      viewBox="0 0 800 600"
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <linearGradient id="retro-fade" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="white" stopOpacity="0" />
          <stop offset="0.55" stopColor="white" stopOpacity="0" />
          <stop offset="1" stopColor="white" stopOpacity="1" />
        </linearGradient>
        <mask id="retro-grid-mask">
          <rect x="0" y="300" width="800" height="300" fill="url(#retro-fade)" />
        </mask>
      </defs>
      <g mask="url(#retro-grid-mask)" opacity="0.22">
        <g ref={gridRef}>
          {ROW_YS.map((y) => (
            <line key={y} x1="0" y1={y} x2="800" y2={y} stroke="var(--accent)" strokeWidth="1" />
          ))}
        </g>
      </g>
      <g ref={motesRef}>
        {Array.from({ length: MOTE_COUNT }).map((_, i) => (
          <rect
            key={i}
            className="retro-mote"
            x={70 + i * 115}
            y={60 + (i % 3) * 55}
            width="4"
            height="4"
            fill="var(--accent)"
            opacity="0.18"
          />
        ))}
      </g>
    </svg>
  );
}
