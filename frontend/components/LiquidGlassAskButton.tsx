"use client";

import { useEffect, useRef } from "react";
import { loadLiquidGlass } from "@/lib/loadLiquidGlass";
import "@/app/liquid-glass.css";

// A real liquid-glass-js Button (github.com/dashersw/liquid-glass-js,
// MIT, vendored under public/vendor/liquid-glass/ -- it ships only as
// plain <script> globals, not an npm package, so there is nothing for
// npm to install). WebGL, refracting an html2canvas snapshot of the
// real page behind it, not a CSS approximation.
//
// Why this is its own component instead of the library wrapping the
// existing <button>: liquid-glass-js's Button fully owns the DOM
// subtree it creates (its own text node, its own click listener) --
// addChild()/its constructor re-parent whatever element you hand it
// into the library's own tree, which is exactly the kind of DOM surgery
// that crashes React's reconciler if it later tries to remove a node
// from where it thinks that node still lives. So React is only ever
// responsible for the empty <div> below (a single real useRef<HTMLDivElement>,
// the one pattern this project's react-hooks/refs lint rule actually
// trusts); the library owns everything inside it, queried fresh via
// querySelector in each effect rather than threaded across effects as a
// stored class-instance ref, which is what that rule objects to.
//
// One real, documented limitation of the library itself, not a bug in
// this integration: the glass refracts a ONE-TIME html2canvas snapshot
// of the page background, cached statically across every instance
// (Container.pageSnapshot), not a live re-render. Fine for this button
// specifically, since nothing behind its own bounding box changes when a
// result streams in further down the page; would NOT be fine for a
// surface whose own background changes after mount (which is exactly
// why this isn't also used for the ask bar's result panel).
//
// A second limitation used to live here: the library shipped with no
// destroy/cleanup method at all, so the scroll listener its render loop
// registers on `window` leaked permanently, once per mount, for the life
// of the page. Fixed directly (Slice 47), not worked around: added a
// real destroy() to the vendored public/vendor/liquid-glass/container.js
// itself (it's vendored source in this repo, not an npm dependency --
// there was nothing stopping this), called from this component's own
// cleanup below.
//
// Text updates (Ask -> Asking...) go straight through the generated
// .glass-button-text node rather than recreating the button, since
// recreating would re-run the same layout/sizing work for no benefit
// once the snapshot is already cached -- constructed once with the
// longer of the two real labels so neither ever visually overflows the
// pill.
export default function LiquidGlassAskButton({
  label,
  disabled,
  onActivate,
}: {
  label: string;
  disabled: boolean;
  onActivate: () => void;
}) {
  const mountRef = useRef<HTMLDivElement>(null);
  const onActivateRef = useRef(onActivate);
  const labelRef = useRef(label);
  const disabledRef = useRef(disabled);

  useEffect(() => {
    onActivateRef.current = onActivate;
    labelRef.current = label;
    disabledRef.current = disabled;
  });

  useEffect(() => {
    let cancelled = false;
    let liveButton: LiquidGlassButtonInstance | null = null;
    const mount = mountRef.current;

    loadLiquidGlass().then(() => {
      if (cancelled || !mount || mount.firstChild || !window.Button) return;
      const activate = () => {
        if (!disabledRef.current) onActivateRef.current();
      };
      const button = new window.Button({
        text: "Asking…", // the longer of the two real labels, purely for
        // initial pill sizing -- immediately corrected below to whatever
        // the real label actually is by the time loading finishes. This
        // matters: script loading (html2canvas + the two vendored files)
        // is genuinely async, so a naive `useEffect(..., [label])` synced
        // to this button's text races it and can find nothing in the DOM
        // yet the one time it matters most, right after first mount.
        size: 15,
        type: "pill",
        tintOpacity: 0.4,
        onClick: activate,
      });
      liveButton = button;
      mount.appendChild(button.element);
      button.textElement.textContent = labelRef.current;
      button.element.style.opacity = disabledRef.current ? "0.4" : "1";
      button.element.style.pointerEvents = disabledRef.current ? "none" : "auto";

      // liquid-glass-js's generated element is a plain, unstyled-for-
      // accessibility <div>: no tabindex, no role, no keyboard handling
      // at all. The <button> this replaced was keyboard-accessible for
      // free; matching that here is this integration's job, not
      // something to silently drop.
      button.element.tabIndex = disabledRef.current ? -1 : 0;
      button.element.setAttribute("role", "button");
      button.element.setAttribute("aria-label", labelRef.current);
      button.element.setAttribute("aria-disabled", String(disabledRef.current));
      button.element.addEventListener("keydown", (e: KeyboardEvent) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          activate();
        }
      });
    });

    return () => {
      cancelled = true;
      // destroy() (Slice 47, added directly to the vendored container.js)
      // removes the render loop's `window` scroll listener and frees the
      // WebGL context explicitly -- previously nothing did either, so
      // every mount of this component leaked both for the life of the
      // page. Optional-chained: a future re-vendoring that drops
      // destroy() again should degrade to the old (still real, still
      // documented) leak, not crash the cleanup.
      liveButton?.destroy?.();
      while (mount?.firstChild) mount.removeChild(mount.firstChild);
    };
    // Constructed once; label/disabled are pushed into the live DOM by
    // the effects below (once mounted) and by the refs above (during the
    // race window before it exists).
  }, []);

  useEffect(() => {
    const el = mountRef.current?.querySelector<HTMLElement>(".glass-button");
    const textEl = mountRef.current?.querySelector<HTMLElement>(".glass-button-text");
    if (textEl) textEl.textContent = label;
    if (el) el.setAttribute("aria-label", label);
  }, [label]);

  useEffect(() => {
    const el = mountRef.current?.querySelector<HTMLElement>(".glass-button");
    if (el) {
      el.style.opacity = disabled ? "0.4" : "1";
      el.style.pointerEvents = disabled ? "none" : "auto";
      el.setAttribute("aria-disabled", String(disabled));
      el.tabIndex = disabled ? -1 : 0;
    }
  }, [disabled]);

  return <div ref={mountRef} className="inline-flex" />;
}
