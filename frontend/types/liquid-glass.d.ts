// Ambient types for liquid-glass-js (github.com/dashersw/liquid-glass-js),
// loaded as plain <script> globals (see lib/loadLiquidGlass.ts), not an
// npm package -- there is no @types package for it, and it ships no
// types of its own. Narrowed to only the shape this project actually
// uses (LiquidGlassAskButton.tsx), not the library's full real API.

interface LiquidGlassButtonOptions {
  text?: string;
  size?: number;
  type?: "rounded" | "circle" | "pill";
  tintOpacity?: number;
  warp?: boolean;
  onClick?: (text: string) => void;
}

interface LiquidGlassButtonInstance {
  element: HTMLDivElement;
  textElement: HTMLDivElement;
  // Added directly to the vendored public/vendor/liquid-glass/container.js
  // (Slice 47) -- the library shipped with no teardown API at all, which
  // is what made its scroll listener leak permanent in the first place.
  // Optional here because it's new: older cached copies of the vendored
  // file (or a future re-vendoring that drops it again) shouldn't hard-
  // crash the caller, just silently skip cleanup -- see
  // LiquidGlassAskButton.tsx's `?.destroy?.()` call site.
  destroy?: () => void;
}

interface Window {
  Button?: new (options: LiquidGlassButtonOptions) => LiquidGlassButtonInstance;
  Container?: new (options: {
    borderRadius?: number;
    type?: "rounded" | "circle" | "pill";
    tintOpacity?: number;
  }) => unknown;
  html2canvas?: (element: HTMLElement, options?: Record<string, unknown>) => Promise<HTMLCanvasElement>;
}
