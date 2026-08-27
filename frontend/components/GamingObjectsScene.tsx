"use client";

import { useMemo, useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { RoundedBox } from "@react-three/drei";
import * as THREE from "three";
import { useReducedMotion } from "@/lib/useReducedMotion";

// The "Meet Ludo" scroll section's visual anchor: five hand-authored 3D
// objects (controller, console, TV, disc, cartridge) — gaming iconography
// this time, not the abstract genre-colored primitives HeroScene.tsx uses.
// Still no external .glb assets, consistent with this project's
// hand-authored-only discipline: each object is a small group of primitive
// geometries (RoundedBox from drei plus core Three.js primitives), not a
// downloaded model. Deliberately NOT colored per the genre palette —
// that palette is load-bearing elsewhere (which color means which genre,
// see globals.css) and reusing it here as pure decoration would imply a
// mapping that doesn't exist. Instead every object shares the same
// restrained treatment as the rest of the UI chrome: a graphite chassis
// (--surface-raised) with the one warm-gold accent (--accent) picking out
// the "active" details (buttons, a screen glow, a disc label).

type Colors = { chassis: string; accent: string; dark: string };

// Chassis is a deliberately hand-picked mid-graphite, NOT --surface-raised
// (the app's near-black panel color) -- found by actually rendering with
// --surface-raised first and getting silhouettes that nearly disappeared
// against the equally-near-black canvas background. HeroScene.tsx's
// objects read fine at that darkness because they're saturated genre
// colors; these are meant to be neutral chassis, which needs real
// lightness contrast against the background to read as a lit object
// instead of a shadow. --accent (the one warm-gold accent) still comes
// from the CSS variable, same as everywhere else in the app.
function useBrandColors(): Colors {
  return useMemo(() => {
    if (typeof window === "undefined") {
      return { chassis: "#6b6f79", accent: "#f0a63a", dark: "#08090a" };
    }
    const style = getComputedStyle(document.documentElement);
    return {
      chassis: "#6b6f79",
      accent: style.getPropertyValue("--accent").trim() || "#f0a63a",
      dark: style.getPropertyValue("--background").trim() || "#08090a",
    };
  }, []);
}

function ChassisMaterial({ colors }: { colors: Colors }) {
  return (
    <meshPhysicalMaterial
      color={colors.chassis}
      roughness={0.35}
      metalness={0.22}
      clearcoat={0.45}
      clearcoatRoughness={0.25}
    />
  );
}

function AccentMaterial({ colors, intensity = 0.2 }: { colors: Colors; intensity?: number }) {
  return (
    <meshPhysicalMaterial
      color={colors.accent}
      roughness={0.3}
      metalness={0.1}
      emissive={colors.accent}
      emissiveIntensity={intensity}
    />
  );
}

function GameController({ colors }: { colors: Colors }) {
  const buttonPositions: [number, number][] = [
    [0.72, 0.13],
    [0.86, -0.02],
    [0.58, -0.02],
    [0.72, -0.17],
  ];
  return (
    <group>
      <RoundedBox args={[1.9, 0.72, 0.32]} radius={0.16} smoothness={4} castShadow>
        <ChassisMaterial colors={colors} />
      </RoundedBox>
      <mesh position={[-0.92, -0.36, 0]} rotation={[0, 0, 0.55]}>
        <capsuleGeometry args={[0.21, 0.5, 6, 16]} />
        <ChassisMaterial colors={colors} />
      </mesh>
      <mesh position={[0.92, -0.36, 0]} rotation={[0, 0, -0.55]}>
        <capsuleGeometry args={[0.21, 0.5, 6, 16]} />
        <ChassisMaterial colors={colors} />
      </mesh>
      <mesh position={[-0.55, 0.06, 0.2]}>
        <cylinderGeometry args={[0.15, 0.15, 0.12, 24]} />
        <AccentMaterial colors={colors} intensity={0.15} />
      </mesh>
      <mesh position={[0.1, -0.18, 0.2]}>
        <cylinderGeometry args={[0.15, 0.15, 0.12, 24]} />
        <AccentMaterial colors={colors} intensity={0.15} />
      </mesh>
      <mesh position={[-0.72, 0.2, 0.18]}>
        <boxGeometry args={[0.2, 0.2, 0.05]} />
        <meshPhysicalMaterial color={colors.dark} roughness={0.5} />
      </mesh>
      {buttonPositions.map(([x, y], i) => (
        <mesh key={i} position={[x, y, 0.2]}>
          <sphereGeometry args={[0.05, 16, 16]} />
          <AccentMaterial colors={colors} intensity={0.25} />
        </mesh>
      ))}
    </group>
  );
}

function GameConsole({ colors }: { colors: Colors }) {
  return (
    <group>
      <RoundedBox args={[0.85, 1.55, 0.5]} radius={0.08} smoothness={4} castShadow>
        <ChassisMaterial colors={colors} />
      </RoundedBox>
      <mesh position={[0, 0.48, 0.26]}>
        <boxGeometry args={[0.85, 0.1, 0.02]} />
        <AccentMaterial colors={colors} intensity={0.3} />
      </mesh>
      <mesh position={[0, -0.5, 0.26]} rotation={[Math.PI / 2, 0, 0]}>
        <cylinderGeometry args={[0.06, 0.06, 0.03, 24]} />
        <AccentMaterial colors={colors} intensity={0.3} />
      </mesh>
    </group>
  );
}

function TVMonitor({ colors }: { colors: Colors }) {
  return (
    <group>
      <RoundedBox args={[1.65, 1.1, 0.12]} radius={0.06} smoothness={4} castShadow>
        <ChassisMaterial colors={colors} />
      </RoundedBox>
      <mesh position={[0, 0.06, 0.07]}>
        <planeGeometry args={[1.4, 0.82]} />
        <meshPhysicalMaterial
          color={colors.accent}
          emissive={colors.accent}
          emissiveIntensity={0.35}
          roughness={0.6}
        />
      </mesh>
      <mesh position={[0, -0.7, 0]}>
        <cylinderGeometry args={[0.045, 0.045, 0.32, 12]} />
        <ChassisMaterial colors={colors} />
      </mesh>
      <mesh position={[0, -0.88, 0]}>
        <cylinderGeometry args={[0.32, 0.32, 0.045, 24]} />
        <ChassisMaterial colors={colors} />
      </mesh>
    </group>
  );
}

function Disc({ colors }: { colors: Colors }) {
  return (
    <group>
      <mesh castShadow>
        <cylinderGeometry args={[0.72, 0.72, 0.04, 48]} />
        <meshPhysicalMaterial color={colors.chassis} metalness={0.45} roughness={0.35} clearcoat={0.6} />
      </mesh>
      <mesh position={[0, 0.021, 0]}>
        <cylinderGeometry args={[0.13, 0.13, 0.01, 32]} />
        <meshBasicMaterial color={colors.dark} />
      </mesh>
      <mesh position={[0, 0.021, 0]} rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[0.72, 0.015, 8, 48]} />
        <AccentMaterial colors={colors} intensity={0.2} />
      </mesh>
    </group>
  );
}

function Cartridge({ colors }: { colors: Colors }) {
  return (
    <group>
      <RoundedBox args={[0.82, 1.05, 0.22]} radius={0.05} smoothness={4} castShadow>
        <ChassisMaterial colors={colors} />
      </RoundedBox>
      <mesh position={[0, 0.16, 0.12]}>
        <boxGeometry args={[0.62, 0.52, 0.02]} />
        <AccentMaterial colors={colors} intensity={0.2} />
      </mesh>
      <mesh position={[0, -0.55, 0]}>
        <boxGeometry args={[0.66, 0.1, 0.24]} />
        <meshPhysicalMaterial color={colors.dark} roughness={0.5} />
      </mesh>
    </group>
  );
}

type RigSpec = {
  position: [number, number, number];
  scale: number;
  spinAxis: [number, number, number];
  spinSpeed: number;
};

const RIGS: RigSpec[] = [
  { position: [-3.6, 0.3, -0.5], scale: 0.95, spinAxis: [0.25, 1, 0.15], spinSpeed: 0.1 },
  { position: [-1.8, -0.5, 0.5], scale: 0.85, spinAxis: [0.2, 0.6, 0.1], spinSpeed: 0.08 },
  { position: [0, 0.55, -0.8], scale: 0.95, spinAxis: [0.15, 0.4, 0.1], spinSpeed: 0.07 },
  { position: [1.8, -0.4, 0.4], scale: 1.0, spinAxis: [0.4, 1, 0.25], spinSpeed: 0.16 },
  { position: [3.6, 0.25, -0.4], scale: 0.9, spinAxis: [0.2, 0.7, 0.15], spinSpeed: 0.11 },
];

function FloatingRig({
  spec,
  index,
  reduceMotion,
  children,
}: {
  spec: RigSpec;
  index: number;
  reduceMotion: boolean;
  children: React.ReactNode;
}) {
  const ref = useRef<THREE.Group>(null);
  const bobOffset = index * 1.9;

  useFrame((state, delta) => {
    if (!ref.current || reduceMotion) return;
    ref.current.rotation.x += spec.spinAxis[0] * spec.spinSpeed * delta;
    ref.current.rotation.y += spec.spinAxis[1] * spec.spinSpeed * delta;
    ref.current.rotation.z += spec.spinAxis[2] * spec.spinSpeed * delta;
    ref.current.position.y = spec.position[1] + Math.sin(state.clock.elapsedTime * 0.5 + bobOffset) * 0.1;
  });

  return (
    <group ref={ref} position={spec.position} scale={spec.scale}>
      {children}
    </group>
  );
}

const OBJECT_COMPONENTS = [GameController, GameConsole, TVMonitor, Disc, Cartridge];

export default function GamingObjectsScene() {
  const reduceMotion = useReducedMotion();
  const colors = useBrandColors();

  return (
    <Canvas
      dpr={[1, 2]}
      camera={{ position: [0, 0, 8.5], fov: 45 }}
      gl={{ antialias: true, alpha: true }}
      className="!absolute inset-0"
    >
      <ambientLight intensity={0.75} />
      <directionalLight position={[4, 5, 5]} intensity={1.3} />
      <directionalLight position={[-4, -2, -3]} intensity={0.4} color="#8fb3ff" />
      <pointLight position={[0, 1, 5]} intensity={0.5} color="#f0a63a" />
      {RIGS.map((spec, i) => {
        const ObjectComponent = OBJECT_COMPONENTS[i];
        return (
          <FloatingRig key={i} spec={spec} index={i} reduceMotion={reduceMotion}>
            <ObjectComponent colors={colors} />
          </FloatingRig>
        );
      })}
    </Canvas>
  );
}
