"use client";

import { ShaderGradient, ShaderGradientCanvas } from "@shadergradient/react";

// A real animated 3D gradient (Three.js/WebGL via @shadergradient/react,
// github.com/ruucm/shadergradient), not a CSS approximation -- colors
// are this app's own accent green (--accent, #39ff88, darkened) and a
// deep turquoise, over its own near-black background (--background,
// #0a0f0b), not the library's stock presets, so it reads as this app's
// identity rather than a borrowed demo.
//
// The scrim div is load-bearing, not decoration: a first pass without
// it (brightness 1.1, saturated colors straight from the design tokens)
// rendered the hero's own body text almost unreadable against the
// gradient's brighter frames -- checked with a real screenshot, not
// assumed. Dimmed the shader itself (lower brightness, darker color1/
// color2) AND layered a semi-transparent dark scrim on top of the
// canvas, rather than relying on either alone: the shader still moves
// and reads as a real animated gradient underneath, but text contrast
// no longer depends on which exact frame is showing.
//
// Mounted only from app/page.tsx (via next/dynamic, ssr:false -- WebGL
// needs a real browser context), never from layout.tsx: the catalog
// page's dense data table needs a quiet background to stay readable,
// matching this project's existing instinct to spend a visual flourish
// in one place rather than everywhere (the same reasoning FilmStrip's
// hero treatment and the genre palette validation already followed).
//
// Also, as of Slice 47, deliberately NOT rendered on page.tsx's very
// first paint: this component's dynamic import pulls in a real 1.1MB
// three.js/shadergradient chunk, and there was previously nothing
// deferring *when* that fetch+parse+execute happened, so it competed
// with the hero's own critical content for bandwidth/main-thread time on
// every visit. page.tsx gates rendering this behind useDeferredMount()
// (lib/useDeferredMount.ts) instead, so the real content paints first.
export default function GradientBackground() {
  return (
    <>
      <ShaderGradientCanvas
        style={{ position: "fixed", inset: 0, zIndex: -2 }}
        pointerEvents="none"
        pixelDensity={1}
        fov={45}
      >
        <ShaderGradient
          type="waterPlane"
          animate="on"
          color1="#0e5c38"
          color2="#0d3b3f"
          color3="#0a0f0b"
          uSpeed={0.15}
          uStrength={2.4}
          uDensity={1.2}
          uFrequency={5.5}
          uAmplitude={1.8}
          reflection={0.08}
          grain="on"
          brightness={0.85}
          cDistance={6.5}
          cPolarAngle={90}
          cAzimuthAngle={180}
          cameraZoom={1}
          positionY={-0.4}
        />
      </ShaderGradientCanvas>
      <div
        aria-hidden="true"
        style={{
          position: "fixed",
          inset: 0,
          zIndex: -1,
          pointerEvents: "none",
          background:
            "radial-gradient(ellipse 70% 45% at 50% 8%, rgba(10,15,11,0.55), rgba(10,15,11,0.25) 60%, rgba(10,15,11,0.55) 100%)",
        }}
      />
    </>
  );
}
