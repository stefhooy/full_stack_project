"use client";

import { useEffect, useState } from "react";

// Flips true once the browser is actually idle (or, failing that, after a
// short timeout), so a caller can hold off mounting something non-critical
// -- a decorative background, say -- until the page's real content has had
// its first paint, instead of competing with it on the very first render.
//
// Written for GradientBackground (Slice 47): that component's own dynamic
// import pulls in a real 1.1MB three.js/shadergradient chunk, and nothing
// was previously deferring *when* that fetch+parse+execute happened --
// next/dynamic's ssr:false keeps it out of the server render, but the
// client still fetched and mounted it immediately regardless, on every
// visit to "/", for a pure visual flourish behind the hero text.
//
// requestIdleCallback isn't implemented in every browser (notably Safari,
// as of this writing) -- setTimeout is the honest fallback there: not a
// real idle signal, but still strictly better than mounting synchronously
// on first render everywhere that lacks it.
export function useDeferredMount(timeoutMs = 200): boolean {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const ric = window.requestIdleCallback;
    if (typeof ric === "function") {
      const id = ric(() => setReady(true), { timeout: timeoutMs });
      return () => window.cancelIdleCallback?.(id);
    }
    const id = window.setTimeout(() => setReady(true), timeoutMs);
    return () => window.clearTimeout(id);
  }, [timeoutMs]);

  return ready;
}
