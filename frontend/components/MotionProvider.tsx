"use client";

import { MotionConfig } from "motion/react";
import type { ReactNode } from "react";

// reducedMotion="user" makes every motion.* animation in the tree honor
// prefers-reduced-motion automatically (positional animations become
// instant; opacity/color transitions stay) — one line covers the whole app
// instead of checking the media query in each component.
export default function MotionProvider({ children }: { children: ReactNode }) {
  return <MotionConfig reducedMotion="user">{children}</MotionConfig>;
}
