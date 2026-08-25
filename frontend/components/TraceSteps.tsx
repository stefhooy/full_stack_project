"use client";

import { motion } from "motion/react";

// Turns the streamed progress events into the same node-by-node "trace"
// visual used in ARCHITECTURE.md's agent diagram/artifact, instead of a
// flat scrolling text log. STEPS is the graph's happy-path node order (see
// src/agent/graph.py's build_graph()) — lookup, analysis, AND forecast all
// flow through this exact same path now (forecast used to be its own
// terminal node; see graph.py's module docstring for why that changed).
// execute_tools can repeat (the self-correction retry loop) — a repeat
// visit just re-pulses that same dot rather than adding a new one, same as
// the interactive artifact does. ask_clarification is the one remaining
// alternate terminal (too-ambiguous questions never enter this pipeline).
const STEPS: { node: string; label: string }[] = [
  { node: "router", label: "route" },
  { node: "retrieve_schema", label: "schema" },
  { node: "agent", label: "think" },
  { node: "execute_tools", label: "query" },
  { node: "build_chart_spec", label: "chart" },
];

const TERMINAL_LABELS: Record<string, string> = {
  ask_clarification: "clarify",
};

export default function TraceSteps({
  visited,
  current,
}: {
  visited: string[];
  current: string | null;
}) {
  const terminalNode = visited.find((n) => n in TERMINAL_LABELS);
  const lastRegularIndex = terminalNode
    ? -1
    : STEPS.reduce(
        (acc, s, i) => (visited.includes(s.node) ? i : acc),
        -1
      );

  return (
    <div className="flex items-center gap-0" aria-label="agent execution trace">
      {STEPS.map((s, i) => {
        const isVisited = !terminalNode && visited.includes(s.node);
        const isCurrent = !terminalNode && current === s.node;
        const isPast = !terminalNode && i < lastRegularIndex;
        return (
          <div key={s.node} className="flex items-center">
            <div className="flex flex-col items-center gap-1.5 w-14">
              <motion.div
                className="h-2 w-2 rounded-full"
                animate={{
                  backgroundColor: isVisited ? "var(--accent)" : "var(--border-strong)",
                  scale: isCurrent ? [1, 1.3, 1] : 1,
                  boxShadow: isVisited
                    ? "0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent)"
                    : "0 0 0 0px transparent",
                }}
                transition={
                  isCurrent
                    ? { duration: 0.9, repeat: Infinity, ease: "easeInOut" }
                    : { duration: 0.3 }
                }
              />
              <span
                className={`font-mono text-[10px] tracking-wide transition-colors ${
                  isVisited ? "text-[var(--foreground)]" : "text-[var(--muted)]"
                } ${isPast ? "opacity-60" : ""}`}
              >
                {s.label}
              </span>
            </div>
            {i < STEPS.length - 1 && (
              <motion.div
                className="h-px w-6 sm:w-9 -mt-4"
                animate={{
                  backgroundColor:
                    !terminalNode && i < lastRegularIndex ? "var(--accent)" : "var(--border)",
                }}
                transition={{ duration: 0.3 }}
              />
            )}
          </div>
        );
      })}
      {terminalNode && (
        <motion.span
          initial={{ opacity: 0, x: -6 }}
          animate={{ opacity: 1, x: 0 }}
          className="ml-2 font-mono text-[10px] tracking-wide text-[var(--accent)] -mt-4"
        >
          → {TERMINAL_LABELS[terminalNode]}
        </motion.span>
      )}
    </div>
  );
}
