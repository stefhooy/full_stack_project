"use client";

import { useEffect, useMemo, useRef, useSyncExternalStore } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import * as THREE from "three";

// Subscribes to the live prefers-reduced-motion value via
// useSyncExternalStore — the textbook-correct way to read a synchronous
// external browser API that can change after mount (matchMedia doesn't
// have a React-friendly hook of its own), rather than a one-shot
// useEffect+setState that both misses later toggles and trips the
// set-state-in-effect lint rule for no real benefit.
function subscribeReducedMotion(callback: () => void) {
  const mql = window.matchMedia("(prefers-reduced-motion: reduce)");
  mql.addEventListener("change", callback);
  return () => mql.removeEventListener("change", callback);
}
function getReducedMotionSnapshot() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
function getReducedMotionServerSnapshot() {
  return false;
}
function useReducedMotion() {
  return useSyncExternalStore(
    subscribeReducedMotion,
    getReducedMotionSnapshot,
    getReducedMotionServerSnapshot
  );
}

// The hero's one visual flourish, replacing the previous synthwave scene
// entirely: a small cluster of real, lit 3D objects (WebGL via React Three
// Fiber — not CSS 3D transforms, which can tilt a flat plane but can't
// give an object actual shaded volume) in the genre categorical palette.
// Deliberately abstract primitives, not literal game-controller/dice
// models — no external .glb assets, consistent with this project's
// hand-authored-only discipline for the 2D genre icons. This is a
// decorative ensemble representing "the catalog's variety," not a 1:1
// mapping to specific genre names (the genre picker below does that
// literal, real-data job already).
//
// Colors are read from the CSS custom properties at mount (not
// re-declared as a parallel hex list) so this stays the same
// single-source-of-truth as every 2D use of the genre palette.

type ObjectSpec = {
  position: [number, number, number];
  scale: number;
  geometry: "icosahedron" | "octahedron" | "torus" | "box" | "capsule" | "cone";
  colorVar: string;
  spinAxis: [number, number, number];
  spinSpeed: number;
};

const OBJECTS: ObjectSpec[] = [
  { position: [1.6, 0.6, 0], scale: 1.05, geometry: "icosahedron", colorVar: "--genre-1", spinAxis: [0.4, 1, 0.2], spinSpeed: 0.18 },
  { position: [-1.5, -0.5, -0.6], scale: 0.85, geometry: "octahedron", colorVar: "--genre-2", spinAxis: [1, 0.3, 0.1], spinSpeed: 0.24 },
  { position: [0.3, 1.4, -1], scale: 0.6, geometry: "torus", colorVar: "--genre-3", spinAxis: [0.6, 1, 0.4], spinSpeed: 0.3 },
  { position: [-0.6, 0.4, 1.1], scale: 0.5, geometry: "box", colorVar: "--genre-4", spinAxis: [0.3, 0.7, 1], spinSpeed: 0.22 },
  { position: [1.4, -1.1, 0.6], scale: 0.65, geometry: "capsule", colorVar: "--genre-7", spinAxis: [1, 0.2, 0.5], spinSpeed: 0.16 },
  { position: [-1.6, 1.2, 0.4], scale: 0.45, geometry: "cone", colorVar: "--genre-5", spinAxis: [0.2, 1, 0.3], spinSpeed: 0.28 },
];

function geometryFor(kind: ObjectSpec["geometry"]) {
  switch (kind) {
    case "icosahedron":
      return <icosahedronGeometry args={[1, 0]} />;
    case "octahedron":
      return <octahedronGeometry args={[1, 0]} />;
    case "torus":
      return <torusGeometry args={[0.8, 0.3, 24, 64]} />;
    case "box":
      return <boxGeometry args={[1.3, 1.3, 1.3]} />;
    case "capsule":
      return <capsuleGeometry args={[0.5, 1, 6, 16]} />;
    case "cone":
      return <coneGeometry args={[0.9, 1.5, 32]} />;
  }
}

function FloatingObject({
  spec,
  index,
  reduceMotion,
}: {
  spec: ObjectSpec;
  index: number;
  reduceMotion: boolean;
}) {
  const ref = useRef<THREE.Mesh>(null);
  const color = useMemo(() => {
    if (typeof window === "undefined") return "#888888";
    return getComputedStyle(document.documentElement).getPropertyValue(spec.colorVar).trim() || "#888888";
  }, [spec.colorVar]);
  // Deterministic per-object phase offset (not Math.random() — impure
  // calls aren't allowed during render) so each object bobs out of sync
  // with the others without needing real randomness for what's just
  // visual variety.
  const bobOffset = index * 1.7;

  useFrame((state, delta) => {
    if (!ref.current || reduceMotion) return;
    ref.current.rotation.x += spec.spinAxis[0] * spec.spinSpeed * delta;
    ref.current.rotation.y += spec.spinAxis[1] * spec.spinSpeed * delta;
    ref.current.rotation.z += spec.spinAxis[2] * spec.spinSpeed * delta;
    ref.current.position.y = spec.position[1] + Math.sin(state.clock.elapsedTime * 0.6 + bobOffset) * 0.12;
  });

  return (
    <mesh ref={ref} position={spec.position} scale={spec.scale} castShadow receiveShadow>
      {geometryFor(spec.geometry)}
      <meshPhysicalMaterial
        color={color}
        roughness={0.28}
        metalness={0.15}
        clearcoat={0.4}
        clearcoatRoughness={0.25}
        emissive={color}
        emissiveIntensity={0.08}
      />
    </mesh>
  );
}

function Parallax({ reduceMotion }: { reduceMotion: boolean }) {
  const target = useRef({ x: 0, y: 0 });

  useEffect(() => {
    if (reduceMotion) return;
    const handler = (e: PointerEvent) => {
      target.current.x = (e.clientX / window.innerWidth - 0.5) * 2;
      target.current.y = (e.clientY / window.innerHeight - 0.5) * 2;
    };
    window.addEventListener("pointermove", handler);
    return () => window.removeEventListener("pointermove", handler);
  }, [reduceMotion]);

  // Reads `state.camera` from the useFrame callback rather than
  // destructuring `camera` from useThree() at the top of the component —
  // R3F's whole per-frame model is imperative mutation of objects it
  // hands you outside React's own render cycle (that's what useFrame is
  // for), which the newer "don't mutate a hook's return value" lint rule
  // doesn't have a way to know is safe here.
  useFrame((state) => {
    if (reduceMotion) return;
    state.camera.position.x += (target.current.x * 0.6 - state.camera.position.x) * 0.04;
    state.camera.position.y += (-target.current.y * 0.4 - state.camera.position.y) * 0.04;
    state.camera.lookAt(0, 0, 0);
  });

  return null;
}

export default function HeroScene() {
  const reduceMotion = useReducedMotion();

  return (
    <Canvas
      dpr={[1, 2]}
      camera={{ position: [0, 0, 6], fov: 42 }}
      gl={{ antialias: true, alpha: true }}
      className="!absolute inset-0"
    >
      <ambientLight intensity={0.55} />
      <directionalLight position={[4, 5, 4]} intensity={1.1} />
      <directionalLight position={[-4, -2, -3]} intensity={0.35} color="#8fb3ff" />
      <pointLight position={[0, 0, 4]} intensity={0.4} color="#f0a63a" />
      <Parallax reduceMotion={reduceMotion} />
      {OBJECTS.map((spec, i) => (
        <FloatingObject key={i} spec={spec} index={i} reduceMotion={reduceMotion} />
      ))}
    </Canvas>
  );
}
