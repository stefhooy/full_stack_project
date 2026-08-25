"use client";

import { useEffect, useRef } from "react";
import { animate } from "animejs";

// The full synthwave scene: gradient sky, a striped glowing sun, low-poly
// mountain silhouettes, and a neon grid horizon (converging perspective
// lines, static, plus animated horizontal scan-lines scrolling toward the
// viewer). Built from a specific reference image, not a generic "retro"
// gesture. See DOCEXP.md for the fuller story.
//
// The viewBox is taller than the viewport (800x900, not 800x600) and uses
// `xMidYMid slice` rather than `xMidYMax`: with a bottom-anchored viewBox,
// where the horizon/sun land on screen depends on how much the viewport's
// aspect ratio happens to overflow vertically — on a typical wide/short
// desktop viewport that pushed the sun up behind the hero copy instead of
// centering it. Centering the mapping instead means the horizon (y=450,
// the exact viewBox middle) always lands at the vertical center of
// whatever viewport it's rendered in, not wherever the aspect-ratio math
// happens to put it. The ground/grid are drawn well past the viewBox's own
// bottom edge (to y=1000) so there's no visible gap under any real
// viewport's crop.
//
// Anime.js drives the two animated pieces (the grid scroll, the drifting
// motes) — still the one place in the app it's used, still for the same
// reason as before: an imperative, non-interactive ambient loop with no
// React state involved, which isn't Motion's job. Motion still owns every
// state-driven UI transition everywhere else in the app.

const HORIZON = 450;
const GROUND_BOTTOM = 1000;

const ROW_HEIGHT = 54;
// Rows start above the horizon (masked out until they scroll into view) so
// translating by exactly one row-height and looping reads as continuous
// scroll — there's always another row already in place where the last one
// left off.
const ROW_YS = Array.from({ length: 12 }, (_, i) => HORIZON - ROW_HEIGHT + i * ROW_HEIGHT);

// Converging verticals, fanned from the vanishing point out past both
// viewBox edges at the bottom — the "endless road" half of the perspective
// grid. Static (no animation needed; only the horizontals scroll).
const VANISH = { x: 400, y: HORIZON };
const VERTICAL_BOTTOM_XS = Array.from({ length: 21 }, (_, i) => -800 + i * 100);

// Low-poly mountain silhouettes — two layers, each a simple jagged
// polyline computed from a small deterministic zigzag rather than
// hand-typed path data.
function ridge(baseY: number, amplitude: number, seed: number): string {
  const points: string[] = [`0,${HORIZON}`];
  const n = 14;
  for (let i = 0; i <= n; i++) {
    const x = (800 / n) * i;
    const wobble = Math.sin(i * 1.7 + seed) * amplitude + Math.sin(i * 0.6 + seed * 2) * (amplitude * 0.5);
    points.push(`${x.toFixed(1)},${(baseY - Math.abs(wobble)).toFixed(1)}`);
  }
  points.push(`800,${HORIZON}`);
  return points.join(" ");
}

// Smaller/lower than a first pass that centered the horizon exactly at the
// viewBox middle — that made the sun's brightest band sit right where the
// hero paragraph lives, which no amount of text-shadow fully rescues.
// Biased down and shrunk so the disk's hot upper half stays mostly above
// the text column instead of behind it.
const SUN = { cx: 400, cy: HORIZON + 10, r: 132 };

// The sun's black stripe cutouts, positioned relative to its own center —
// classic "retro scanline sun." Offsets/heights grow going down, same
// proportions as the reference.
const SUN_STRIPES = [
  { dy: -14, h: 12 },
  { dy: 16, h: 15 },
  { dy: 48, h: 18 },
  { dy: 82, h: 21 },
  { dy: 118, h: 24 },
];

const MOTE_COUNT = 5;

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
          duration: 2400,
          loop: true,
          ease: "linear",
        })
      );
    }

    if (motesRef.current) {
      const motes = motesRef.current.querySelectorAll<SVGCircleElement>(".retro-mote");
      motes.forEach((mote, i) => {
        animations.push(
          animate(mote, {
            translateY: [0, -16, 0],
            opacity: [0.25, 0.65, 0.25],
            duration: 4600 + i * 540,
            delay: i * 300,
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
      preserveAspectRatio="xMidYMid slice"
      viewBox={`0 0 800 ${GROUND_BOTTOM}`}
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <linearGradient id="rw-sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#140826" />
          <stop offset="0.42" stopColor="#3a1155" />
          <stop offset="0.68" stopColor="#8a1f7a" />
          <stop offset="0.86" stopColor="#e0447f" />
          <stop offset="1" stopColor="#ff9a4d" />
        </linearGradient>
        <radialGradient id="rw-sun" cx="0.5" cy="0.5" r="0.5">
          <stop offset="0" stopColor="#fff6d6" />
          <stop offset="0.45" stopColor="#ffd76a" />
          <stop offset="0.8" stopColor="#ff9a4d" />
          <stop offset="1" stopColor="#ff6f9c" />
        </radialGradient>
        <linearGradient id="rw-fade" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="white" stopOpacity="0" />
          <stop offset="1" stopColor="white" stopOpacity="1" />
        </linearGradient>
        <mask id="rw-grid-mask">
          <rect x="0" y={HORIZON} width="800" height={GROUND_BOTTOM - HORIZON} fill="url(#rw-fade)" />
        </mask>
        <mask id="rw-sun-stripes">
          <rect
            x={SUN.cx - SUN.r - 30}
            y={SUN.cy - SUN.r - 30}
            width={(SUN.r + 30) * 2}
            height={(SUN.r + 30) * 2}
            fill="white"
          />
          {SUN_STRIPES.map((s) => (
            <rect
              key={s.dy}
              x={SUN.cx - SUN.r - 30}
              y={SUN.cy + s.dy}
              width={(SUN.r + 30) * 2}
              height={s.h}
              fill="black"
            />
          ))}
        </mask>
      </defs>

      {/* sky */}
      <rect x="0" y="0" width="800" height={GROUND_BOTTOM} fill="url(#rw-sky)" />

      {/* sun */}
      <circle cx={SUN.cx} cy={SUN.cy} r={SUN.r} fill="url(#rw-sun)" mask="url(#rw-sun-stripes)" opacity="0.9" />

      {/* mountains */}
      <polygon points={`0,${HORIZON} ${ridge(HORIZON - 28, 34, 1.3)} 800,${HORIZON}`} fill="#2a1045" opacity="0.85" />
      <polygon points={`0,${HORIZON} ${ridge(HORIZON - 14, 22, 4.1)} 800,${HORIZON}`} fill="#180a2c" opacity="0.9" />

      {/* ground plane so the grid has a solid floor beneath it */}
      <rect x="0" y={HORIZON} width="800" height={GROUND_BOTTOM - HORIZON} fill="#12081f" />

      {/* perspective grid */}
      <g mask="url(#rw-grid-mask)">
        {VERTICAL_BOTTOM_XS.map((x) => (
          <line
            key={x}
            x1={VANISH.x}
            y1={VANISH.y}
            x2={x}
            y2={GROUND_BOTTOM}
            stroke="#ff4fc3"
            strokeWidth="1.2"
            opacity="0.55"
          />
        ))}
        <g ref={gridRef}>
          {ROW_YS.map((y) => (
            <line key={y} x1="0" y1={y} x2="800" y2={y} stroke="#ff4fc3" strokeWidth="1.4" opacity="0.65" />
          ))}
        </g>
      </g>

      {/* drifting motes, upper sky */}
      <g ref={motesRef}>
        {Array.from({ length: MOTE_COUNT }).map((_, i) => (
          <circle
            key={i}
            className="retro-mote"
            cx={90 + i * 165}
            cy={90 + (i % 3) * 55}
            r="2.4"
            fill="#fff6d6"
            opacity="0.4"
          />
        ))}
      </g>
    </svg>
  );
}
