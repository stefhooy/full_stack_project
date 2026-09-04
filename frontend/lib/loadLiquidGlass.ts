// Loads liquid-glass-js's real dependency chain in the strict order it
// requires: html2canvas must exist on window before container.js runs
// (it calls html2canvas(...) directly), and container.js must define the
// global Container class before button.js runs ("class Button extends
// Container"). next/script's built-in ordering isn't reliable enough to
// depend on for this, since afterInteractive scripts can load in
// parallel -- so this loads them explicitly, one at a time, each waiting
// on the previous script's actual load event, and caches the resulting
// promise so a second caller (e.g. React Strict Mode's double-invoked
// effect in dev) reuses it instead of injecting duplicate <script> tags.

let loadPromise: Promise<void> | null = null;

function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[src="${src}"]`);
    if (existing) {
      resolve();
      return;
    }
    const script = document.createElement("script");
    script.src = src;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`Failed to load ${src}`));
    document.head.appendChild(script);
  });
}

function bridgeToWindow(): void {
  // container.js/button.js declare `class Container`/`class Button` at
  // the top level of a classic (non-module) script. That creates a
  // binding in the shared global *lexical* scope -- reachable as a bare
  // identifier from another classic script in the same document -- but,
  // unlike `var`, it is NOT added as a property of `window` itself. This
  // inline script runs in that same shared scope, so `Container`/`Button`
  // resolve here as bare identifiers, and explicitly assigns them onto
  // `window` where the rest of this app (a real ES module, a genuinely
  // separate scope) can actually reach them.
  const bridge = document.createElement("script");
  bridge.textContent = "window.Container = Container; window.Button = Button;";
  document.head.appendChild(bridge);
}

export function loadLiquidGlass(): Promise<void> {
  if (loadPromise) return loadPromise;
  loadPromise = loadScript("https://cdn.jsdelivr.net/npm/html2canvas@1.4.1/dist/html2canvas.min.js")
    .then(() => loadScript("/vendor/liquid-glass/container.js"))
    .then(() => loadScript("/vendor/liquid-glass/button.js"))
    .then(() => bridgeToWindow());
  return loadPromise;
}
