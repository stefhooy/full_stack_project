"use client";

import { motion } from "motion/react";

// Turns the streamed progress events into the same node-by-node "trace"
// visual used in ARCHITECTURE.md's agent diagram/artifact, instead of a
// flat scrolling text log. STEPS is the graph's happy-path node order (see
// src/agent/graph.py's build_graph()); build_chart_spec/forecast/clarify
// are alternate terminal nodes so only one of the last three ever lights up
// per run. execute_tools can repeat (the self-correction retry loop) — a
// repeat visit just re-pulses that same dot rather than adding a new one,
// same as the interactive artifact does.
const STEPS: { node: string; label: string }[] = [
  { node: "router", label: "route" },
  { node: "retrieve_schema", label: "schema" },
  { node: "agent", label: "think" },
  { node: "execute_tools", label: "query" },
  { node: "build_chart_spec", label: "chart" },
];

const TERMINAL_LABELS: Record<string, string> = {
  forecast_not_supported: "not supported",
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
                className="h-2.5 w-2.5 rounded-full"
                animate={{
                  backgroundColor: isVisited ? "var(--accent)" : "var(--border)",
                  scale: isCurrent ? [1, 1.35, 1] : 1,
                  boxShadow: isVisited
                    ? "0 0 0 4px var(--accent-glow)"
                    : "0 0 0 0px transparent",
                }}
                transition={
                  isCurrent
                    ? { duration: 0.9, repeat: Infinity, ease: "easeInOut" }
                    : { duration: 0.3 }
                }
              />
              <span
                className={`text-[10px] font-mono uppercase tracking-wide transition-colors ${
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
          className="ml-2 text-[10px] font-mono uppercase tracking-wide text-[var(--accent)] -mt-4"
        >
          → {TERMINAL_LABELS[terminalNode]}
        </motion.span>
      )}
    </div>
  );
}
