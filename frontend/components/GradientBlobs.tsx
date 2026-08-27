"use client";

import { motion } from "motion/react";
import { useReducedMotion } from "@/lib/useReducedMotion";

// Replaces the "Meet Ludo" section's earlier literal 3D gaming-object
// scene (controller/console/TV/disc/cartridge) with a Framer-style
// ambient background: large, softly blurred gradient orbs drifting behind
// the copy, plus a faint grain overlay so the blur doesn't read as flat
// color banding. Pure CSS + Motion, no WebGL — lighter than the R3F scene
// it replaces, and the look this section actually asked for (framer.com's
// own marketing pages lean on exactly this kind of soft glowing color
// field rather than literal 3D objects).
//
// All three orbs are shades of the one site accent (--accent, turquoise)
// at low opacity — same "one confident accent" discipline as the rest of
// the chrome, not a rainbow gradient.

const ORBS = [
  { size: 420, top: "-10%", left: "8%", color: "var(--accent)", opacity: 0.35, duration: 22 },
  { size: 340, top: "20%", left: "62%", color: "#22b8a3", opacity: 0.3, duration: 26 },
  { size: 300, top: "45%", left: "30%", color: "#7fe8d8", opacity: 0.22, duration: 19 },
];

// A single tileable turbulence-noise data URI, generated once at module
// scope (not per-render) -- an inline SVG feTurbulence filter rendered to
// a tiny pattern, same technique Framer/Linear-adjacent sites use to keep
// a large blurred gradient from banding.
const NOISE_SVG =
  "data:image/svg+xml;utf8," +
  encodeURIComponent(
    `<svg xmlns='http://www.w3.org/2000/svg' width='120' height='120'>
      <filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/></filter>
      <rect width='100%' height='100%' filter='url(#n)'/>
    </svg>`
  );

export default function GradientBlobs() {
  const reduceMotion = useReducedMotion();

  return (
    <div className="absolute inset-0 overflow-hidden">
      {ORBS.map((orb, i) => (
        <motion.div
          key={i}
          className="absolute rounded-full"
          style={{
            width: orb.size,
            height: orb.size,
            top: orb.top,
            left: orb.left,
            background: orb.color,
            opacity: orb.opacity,
            filter: "blur(70px)",
          }}
          animate={
            reduceMotion
              ? undefined
              : {
                  x: [0, 30, -20, 0],
                  y: [0, -25, 15, 0],
                }
          }
          transition={{
            duration: orb.duration,
            repeat: Infinity,
            ease: "easeInOut",
          }}
        />
      ))}
      <div
        aria-hidden="true"
        className="absolute inset-0 mix-blend-overlay opacity-[0.06]"
        style={{ backgroundImage: `url("${NOISE_SVG}")` }}
      />
    </div>
  );
}
