"use client";

import { useSyncExternalStore } from "react";

// Subscribes to the live prefers-reduced-motion value via
// useSyncExternalStore — the textbook-correct way to read a synchronous
// external browser API that can change after mount (matchMedia doesn't
// have a React-friendly hook of its own), rather than a one-shot
// useEffect+setState that both misses later toggles and trips the
// set-state-in-effect lint rule for no real benefit. Originally written
// inline in HeroScene.tsx (Slice 9g); pulled out here once a second 3D
// scene (GamingObjectsScene.tsx) needed the exact same hook.
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
