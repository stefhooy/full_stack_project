"use client";

import { useSyncExternalStore } from "react";

// Subscribes to the live prefers-reduced-motion value via
// useSyncExternalStore. Originally written for HeroScene.tsx (Slice 9g),
// deleted in Slice 13 once nothing used it, recreated here in Slice 14
// once AuroraBackground needed the same thing again — worth two sentences
// on that churn: the underlying need (something in this app always wants
// to freeze under reduced-motion) keeps recurring across redesigns even
// though which specific component needs it keeps changing.
function subscribe(callback: () => void) {
  const mql = window.matchMedia("(prefers-reduced-motion: reduce)");
  mql.addEventListener("change", callback);
  return () => mql.removeEventListener("change", callback);
}
function getSnapshot() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
function getServerSnapshot() {
  return false;
}

export function useReducedMotion() {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
