"use client";

import { useEffect, useRef, useState } from "react";

// A small, pure-frontend endless runner shown next to the trace panel
// while Ludo is thinking -- opt-in only (see page.tsx: a "Play while you
// wait" button, never auto-played) so it never distracts anyone who'd
// rather just watch the real trace. Zero network calls, zero Groq
// tokens, and (per the memory-leak lessons from this same session's
// liquid-glass fix) the rAF loop and every listener are torn down
// explicitly on unmount -- nothing here outlives the component.
//
// Deliberately canvas + refs, not react-driven sprites: the game state
// (position, obstacles, score) changes every frame, and routing that
// through useState would re-render the whole tree ~60x/sec. Only the
// score/status text -- what a screen reader or a glance actually needs --
// is mirrored into React state, and only when it changes.

const LOGICAL_WIDTH = 480;
const LOGICAL_HEIGHT = 150;
const GROUND_Y = 110;
const GRAVITY = 1800; // px/s^2
// -620 used to send the sprite's apex above y=0 -- confirmed by an actual
// screenshot at peak height, clipped against the canvas's top edge, not
// just a back-of-envelope worry. -520 keeps a real ~11px of clearance at
// the highest point the physics can reach (v^2/2g), given GROUND_Y=110,
// DINO_SIZE=22, and the sprite's own ~2px overhang above its hitbox.
const JUMP_VELOCITY = -520; // px/s
const DINO_X = 40;
const DINO_SIZE = 22;
const BASE_SPEED = 220; // px/s
const MAX_SPEED = 460;
const SPEED_RAMP_PER_SEC = 6;
const HIGH_SCORE_KEY = "ludo:dino-game:high-score";

type Obstacle = { x: number; width: number; height: number };

type Phase = "idle" | "playing" | "over";

function readHighScore(): number {
  if (typeof window === "undefined") return 0;
  try {
    const raw = window.localStorage.getItem(HIGH_SCORE_KEY);
    return raw ? Number.parseInt(raw, 10) || 0 : 0;
  } catch {
    return 0; // private browsing / storage disabled -- just start at 0
  }
}

function writeHighScore(value: number): void {
  try {
    window.localStorage.setItem(HIGH_SCORE_KEY, String(value));
  } catch {
    // Non-fatal: the game still works, it just won't remember next time.
  }
}

export default function DinoGame() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [score, setScore] = useState(0);
  // Lazy initializer, not an effect -- this component only ever mounts
  // client-side (opt-in, after a user click), so reading localStorage
  // during the initial render is safe and avoids an extra render pass.
  const [highScore, setHighScore] = useState<number>(() => readHighScore());
  const [phase, setPhase] = useState<Phase>("idle");

  // Mutable game state lives in refs -- read/written every animation
  // frame without triggering a re-render.
  const phaseRef = useRef<Phase>("idle");
  const dinoYRef = useRef(0);
  const dinoVYRef = useRef(0);
  const obstaclesRef = useRef<Obstacle[]>([]);
  const distanceRef = useRef(0);
  const speedRef = useRef(BASE_SPEED);
  const spawnTimerRef = useRef(0);
  const legPhaseRef = useRef(0);
  const groundDashesRef = useRef<number[]>([]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context2d = canvas.getContext("2d");
    if (!context2d) return;
    // Re-bound to a variable TS can prove is non-null inside the nested
    // `frame`/closures below -- narrowing a `const` doesn't carry into a
    // hoisted `function` declaration defined later in the same scope.
    const ctx: CanvasRenderingContext2D = context2d;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = LOGICAL_WIDTH * dpr;
    canvas.height = LOGICAL_HEIGHT * dpr;
    ctx.scale(dpr, dpr);

    const style = getComputedStyle(document.documentElement);
    const fgColor = style.getPropertyValue("--foreground").trim() || "#e5e5e5";
    const accentColor = style.getPropertyValue("--accent").trim() || "#22c55e";
    const borderColor = style.getPropertyValue("--border-strong").trim() || "#555";
    const bgColor = style.getPropertyValue("--background").trim() || "#0a0a0a";

    groundDashesRef.current = Array.from(
      { length: 16 },
      (_, i) => (i * LOGICAL_WIDTH) / 16
    );

    function resetGame() {
      dinoYRef.current = GROUND_Y - DINO_SIZE;
      dinoVYRef.current = 0;
      obstaclesRef.current = [];
      distanceRef.current = 0;
      speedRef.current = BASE_SPEED;
      spawnTimerRef.current = 1.1;
      setScore(0);
    }

    function jump() {
      if (phaseRef.current === "idle") {
        resetGame();
        phaseRef.current = "playing";
        setPhase("playing");
        // The tap that starts the run shouldn't also count as a jump
        // input -- falling through to the onGround check below used to
        // do exactly that, so every run started already mid-air.
        return;
      }
      if (phaseRef.current === "over") {
        resetGame();
        phaseRef.current = "playing";
        setPhase("playing");
        return;
      }
      const onGround = dinoYRef.current >= GROUND_Y - DINO_SIZE - 0.5;
      if (phaseRef.current === "playing" && onGround) {
        dinoVYRef.current = JUMP_VELOCITY;
      }
    }

    function onKeyDown(e: KeyboardEvent) {
      const target = e.target as HTMLElement | null;
      const typing = target && ["INPUT", "TEXTAREA"].includes(target.tagName);
      if (typing) return;
      if (e.code === "Space" || e.code === "ArrowUp") {
        e.preventDefault();
        jump();
      }
    }
    function onPointerDown() {
      jump();
    }

    window.addEventListener("keydown", onKeyDown);
    canvas.addEventListener("pointerdown", onPointerDown);

    resetGame();

    let lastScoreShown = 0;
    let rafId = 0;
    let lastTime = performance.now();

    function frame(now: number) {
      const dt = Math.min((now - lastTime) / 1000, 0.05); // clamp big tab-switch gaps
      lastTime = now;

      if (phaseRef.current === "playing") {
        // Physics
        dinoVYRef.current += GRAVITY * dt;
        dinoYRef.current += dinoVYRef.current * dt;
        if (dinoYRef.current > GROUND_Y - DINO_SIZE) {
          dinoYRef.current = GROUND_Y - DINO_SIZE;
          dinoVYRef.current = 0;
        }

        speedRef.current = Math.min(
          MAX_SPEED,
          speedRef.current + SPEED_RAMP_PER_SEC * dt
        );
        distanceRef.current += speedRef.current * dt;

        // Obstacles
        spawnTimerRef.current -= dt;
        if (spawnTimerRef.current <= 0) {
          const height = 18 + Math.random() * 20;
          obstaclesRef.current.push({
            x: LOGICAL_WIDTH + 10,
            width: 12 + Math.random() * 10,
            height,
          });
          spawnTimerRef.current = 0.9 + Math.random() * 0.9;
        }
        for (const obstacle of obstaclesRef.current) {
          obstacle.x -= speedRef.current * dt;
        }
        obstaclesRef.current = obstaclesRef.current.filter((o) => o.x + o.width > -5);

        // Collision (small inset so near-misses feel fair)
        const dinoBox = {
          x: DINO_X + 3,
          y: dinoYRef.current + 3,
          width: DINO_SIZE - 6,
          height: DINO_SIZE - 6,
        };
        for (const obstacle of obstaclesRef.current) {
          const obstacleBox = {
            x: obstacle.x,
            y: GROUND_Y - obstacle.height,
            width: obstacle.width,
            height: obstacle.height,
          };
          const overlap =
            dinoBox.x < obstacleBox.x + obstacleBox.width &&
            dinoBox.x + dinoBox.width > obstacleBox.x &&
            dinoBox.y < obstacleBox.y + obstacleBox.height &&
            dinoBox.y + dinoBox.height > obstacleBox.y;
          if (overlap) {
            phaseRef.current = "over";
            setPhase("over");
            const finalScore = Math.floor(distanceRef.current / 10);
            setScore(finalScore);
            setHighScore((prev) => {
              const next = Math.max(prev, finalScore);
              if (next !== prev) writeHighScore(next);
              return next;
            });
          }
        }

        // Ground dashes scroll for a sense of motion
        groundDashesRef.current = groundDashesRef.current.map((x) => {
          const next = x - speedRef.current * dt;
          return next < -20 ? next + LOGICAL_WIDTH : next;
        });

        legPhaseRef.current += dt;

        const currentScore = Math.floor(distanceRef.current / 10);
        if (currentScore !== lastScoreShown) {
          lastScoreShown = currentScore;
          setScore(currentScore);
        }
      }

      // --- Draw ---
      ctx.clearRect(0, 0, LOGICAL_WIDTH, LOGICAL_HEIGHT);

      // Ground line + scrolling dashes
      ctx.strokeStyle = borderColor;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, GROUND_Y + 0.5);
      ctx.lineTo(LOGICAL_WIDTH, GROUND_Y + 0.5);
      ctx.stroke();
      ctx.fillStyle = borderColor;
      for (const x of groundDashesRef.current) {
        ctx.fillRect(x, GROUND_Y + 4, 8, 2);
      }

      // Dino: a blocky T-rex silhouette (tail, body, neck, head, snout,
      // an eye cutout, and a two-frame running-leg cycle) -- drawn as a
      // fixed set of pixel-art blocks anchored to the sprite's bottom
      // (which lines up with the invisible, slightly-inset collision
      // box computed above; the sprite is deliberately a bit bigger
      // than the hitbox, same "forgiving collisions" convention as the
      // obstacles).
      const bodyY = dinoYRef.current;
      const airborne = bodyY < GROUND_Y - DINO_SIZE - 0.5;
      const legUp = !airborne && Math.floor(legPhaseRef.current / 0.15) % 2 === 0;
      const spriteBottom = bodyY + DINO_SIZE;
      const ox = DINO_X - 2; // sprite origin x
      const oy = spriteBottom - 24; // sprite origin y (24px-tall sprite)

      ctx.fillStyle = fgColor;
      ctx.fillRect(ox + 0, oy + 15, 7, 5); // tail
      ctx.fillRect(ox + 5, oy + 7, 15, 12); // body
      ctx.fillRect(ox + 9, oy + 4, 3, 3); // back ridge bump
      ctx.fillRect(ox + 16, oy + 1, 6, 8); // neck
      ctx.fillRect(ox + 18, oy + 0, 8, 6); // head + snout
      ctx.fillRect(ox + 10, oy + 13, 4, 3); // small arm
      // Legs: tucked and even-length while airborne; alternating stride
      // on the ground for a simple running-cycle illusion.
      const legAHeight = airborne ? 3 : legUp ? 4 : 6;
      const legBHeight = airborne ? 3 : legUp ? 6 : 4;
      ctx.fillRect(ox + 7, oy + 24 - legAHeight, 4, legAHeight);
      ctx.fillRect(ox + 15, oy + 24 - legBHeight, 4, legBHeight);
      // Eye: a small cutout back to the canvas background so it reads
      // against the head block instead of disappearing into it.
      ctx.fillStyle = bgColor;
      ctx.fillRect(ox + 23, oy + 2, 2, 2);

      // Obstacles (cacti)
      ctx.fillStyle = accentColor;
      for (const obstacle of obstaclesRef.current) {
        roundRect(
          ctx,
          obstacle.x,
          GROUND_Y - obstacle.height,
          obstacle.width,
          obstacle.height,
          2
        );
        ctx.fill();
      }

      rafId = requestAnimationFrame(frame);
    }

    rafId = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener("keydown", onKeyDown);
      canvas.removeEventListener("pointerdown", onPointerDown);
    };
  }, []);

  return (
    <div className="mt-3 select-none">
      <div className="mb-1.5 flex items-center justify-between font-mono text-[10px] text-[var(--muted)]">
        <span>{phase === "idle" ? "space / tap to start" : phase === "over" ? "game over, tap to retry" : "space / tap to jump"}</span>
        <span>
          score {score} · best {highScore}
        </span>
      </div>
      <canvas
        ref={canvasRef}
        style={{ width: LOGICAL_WIDTH, height: LOGICAL_HEIGHT, maxWidth: "100%" }}
        className="rounded-lg border border-[var(--border)] bg-[var(--background)] cursor-pointer"
        role="img"
        aria-label={`Dino runner mini-game. Current score ${score}, best ${highScore}. Press space or tap to jump.`}
      />
    </div>
  );
}

function roundRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number
) {
  ctx.beginPath();
  ctx.moveTo(x + radius, y);
  ctx.arcTo(x + width, y, x + width, y + height, radius);
  ctx.arcTo(x + width, y + height, x, y + height, radius);
  ctx.arcTo(x, y + height, x, y, radius);
  ctx.arcTo(x, y, x + width, y, radius);
  ctx.closePath();
}
