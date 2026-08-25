"use client";

import { useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import Chart from "@/components/Chart";
import GenreShowcase from "@/components/GenreShowcase";
import TraceSteps from "@/components/TraceSteps";
import { streamAsk, type AskResult, type StatsResult, type StreamEvent } from "@/lib/api";

const EXAMPLE_QUESTIONS = [
  "What are the 5 highest-rated games with more than 1000 positive reviews?",
  "Is the price difference between Action games and other games statistically significant?",
  "Are there any games with an unusually high number of concurrent players compared to the rest?",
  "How many players will this game have next year?",
];

const ROUTE_LABELS: Record<string, string> = {
  lookup: "Lookup",
  analysis: "Analysis",
  forecast: "Forecast",
  needs_clarification: "Needs clarification",
};

function RouteBadge({ route }: { route: string | null }) {
  if (!route) return null;
  return (
    <span className="inline-flex items-center rounded-full border border-[var(--border)] px-2.5 py-0.5 text-[11px] font-mono uppercase tracking-wide text-[var(--muted)]">
      {ROUTE_LABELS[route] ?? route}
    </span>
  );
}

function StatsResultView({ stats }: { stats: StatsResult }) {
  if (stats.mode === "compare_two_groups") {
    const s = stats as StatsResult & {
      group_a: string;
      group_b: string;
      mean_a: number;
      mean_b: number;
      p_value: number;
      "significant_at_0.05": boolean;
      cohens_d: number;
    };
    return (
      <div className="text-sm space-y-1">
        <div>
          <span className="font-medium">{s.group_a}</span> mean: {s.mean_a.toFixed(2)}
          {"  ·  "}
          <span className="font-medium">{s.group_b}</span> mean: {s.mean_b.toFixed(2)}
        </div>
        <div>
          p-value: {s.p_value.toFixed(4)}{" "}
          <span
            className={
              s["significant_at_0.05"]
                ? "text-emerald-600 dark:text-emerald-400"
                : "text-[var(--muted)]"
            }
          >
            ({s["significant_at_0.05"] ? "significant at 0.05" : "not significant"})
          </span>
          {"  ·  Cohen's d: "}
          {s.cohens_d.toFixed(3)}
        </div>
      </div>
    );
  }

  if (stats.mode === "outliers") {
    const s = stats as StatsResult & {
      outliers: { label: string; value: number; z_score: number }[];
      z_threshold: number;
    };
    return (
      <div className="text-sm">
        <div className="text-[var(--muted)] mb-1">
          outliers beyond z = {s.z_threshold}:
        </div>
        <ul className="space-y-0.5">
          {s.outliers.map((o) => (
            <li key={o.label}>
              <span className="font-medium">{o.label}</span> — {o.value.toLocaleString()}{" "}
              (z = {o.z_score.toFixed(2)})
            </li>
          ))}
        </ul>
      </div>
    );
  }

  // describe
  const s = stats as StatsResult & {
    n: number;
    mean: number;
    median: number;
    stddev: number;
  };
  return (
    <div className="text-sm font-mono">
      n={s.n} · mean={s.mean.toFixed(3)} · median={s.median.toFixed(3)} · stddev=
      {s.stddev.toFixed(3)}
    </div>
  );
}

function ResultTable({ columns, rows }: { columns: string[]; rows: unknown[][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="text-sm border-collapse w-full">
        <thead>
          <tr className="border-b border-[var(--border)]">
            {columns.map((c) => (
              <th key={c} className="text-left py-1.5 pr-4 font-medium text-[var(--muted)]">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-[var(--border)]">
              {row.map((cell, j) => (
                <td key={j} className="py-1.5 pr-4 font-mono">
                  {String(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const heroContainer = {
  hidden: {},
  show: { transition: { staggerChildren: 0.08 } },
};
const heroItem = {
  hidden: { opacity: 0, y: 10 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: [0.16, 1, 0.3, 1] as const } },
};

export default function Home() {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState<Extract<StreamEvent, { type: "progress" }>[]>([]);
  const [result, setResult] = useState<AskResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  async function ask(q: string) {
    if (!q.trim() || loading) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setQuestion(q);
    setLoading(true);
    setProgress([]);
    setResult(null);
    setError(null);

    try {
      await streamAsk(
        q,
        (event) => {
          if (event.type === "progress") {
            setProgress((prev) => [...prev, event]);
          } else if (event.type === "final") {
            setResult(event.result);
          } else {
            setError(event.message);
          }
        },
        controller.signal
      );
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        setError("Couldn't reach the backend. Is it running?");
      }
    } finally {
      setLoading(false);
    }
  }

  const visitedNodes = progress.map((p) => p.node);
  const currentNode = loading ? visitedNodes[visitedNodes.length - 1] ?? null : null;

  return (
    <div className="relative z-[1] min-h-screen font-sans max-w-2xl mx-auto px-6 py-14">
      <motion.div variants={heroContainer} initial="hidden" animate="show">
        <motion.span
          variants={heroItem}
          className="inline-block text-[11px] font-mono uppercase tracking-[0.18em] text-[var(--accent)] mb-3"
        >
          AI Game Analyst
        </motion.span>
        <motion.h1
          variants={heroItem}
          className="text-3xl font-[800] tracking-tight mb-2 text-balance"
        >
          Ask the market a question.
        </motion.h1>
        <motion.p variants={heroItem} className="text-[var(--muted)] text-sm mb-7 max-w-md">
          A tool-using agent writes real SQL, runs real statistics against a
          self-collected game-market dataset, and shows its work — no
          guessing, no canned answers.
        </motion.p>

        <motion.form
          variants={heroItem}
          onSubmit={(e) => {
            e.preventDefault();
            ask(question);
          }}
          className="relative mb-3"
        >
          <div className="flex items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-3 py-1 shadow-sm focus-within:border-[var(--accent)] transition-colors">
            <span className="font-mono text-[var(--accent)] text-sm select-none">›</span>
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="ask about the games catalog..."
              className="flex-1 bg-transparent px-1 py-2.5 text-sm font-mono outline-none placeholder:text-[var(--muted)]"
            />
            <motion.button
              type="submit"
              disabled={loading || !question.trim()}
              whileHover={loading || !question.trim() ? undefined : { scale: 1.04 }}
              whileTap={loading || !question.trim() ? undefined : { scale: 0.96 }}
              className="rounded-lg px-3.5 py-2 text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed"
              style={{ background: "var(--accent)", color: "var(--accent-contrast)" }}
            >
              {loading ? "···" : "Ask"}
            </motion.button>
          </div>
        </motion.form>

        <motion.div variants={heroItem} className="flex flex-wrap gap-1.5 mb-12">
          {EXAMPLE_QUESTIONS.map((q) => (
            <button
              key={q}
              onClick={() => ask(q)}
              disabled={loading}
              className="text-xs px-3 py-1.5 rounded-full border border-[var(--border)] text-[var(--foreground)]/80 hover:border-[var(--accent)] hover:text-[var(--accent)] disabled:opacity-40 transition-colors"
            >
              {q}
            </button>
          ))}
        </motion.div>
      </motion.div>

      <div className="mb-12">
        <GenreShowcase onPick={ask} disabled={loading} />
      </div>

      <AnimatePresence mode="wait">
        {(loading || progress.length > 0) && !result && (
          <motion.div
            key="progress"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="mb-6 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-4 py-4"
          >
            <TraceSteps visited={visitedNodes} current={currentNode} />
          </motion.div>
        )}
      </AnimatePresence>

      {error && (
        <div className="rounded-lg border border-[var(--danger)]/30 bg-[var(--danger-bg)] text-[var(--danger)] text-sm px-4 py-3 mb-4">
          {error}
        </div>
      )}

      <AnimatePresence>
        {result && (
          <motion.div
            key="result"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
            className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5 space-y-4"
          >
            <div className="flex items-center gap-2 flex-wrap">
              <RouteBadge route={result.route} />
              {result.cached && (
                <span className="inline-flex items-center rounded-full border border-[var(--border)] px-2.5 py-0.5 text-[11px] font-mono uppercase tracking-wide text-[var(--muted)]">
                  cached
                </span>
              )}
            </div>

            <p className="text-sm leading-relaxed">{result.answer}</p>

            {result.chart_spec && <Chart spec={result.chart_spec} />}

            {!result.chart_spec && result.columns && result.rows && (
              <ResultTable columns={result.columns} rows={result.rows} />
            )}

            {result.stats_result && <StatsResultView stats={result.stats_result} />}

            {(result.sql || result.retrieved_schema_chunks) && (
              <details className="text-xs text-[var(--muted)]">
                <summary className="cursor-pointer select-none">Show the work</summary>
                <div className="mt-2 space-y-2">
                  {result.sql && (
                    <pre className="whitespace-pre-wrap rounded-lg bg-[var(--background)] border border-[var(--border)] p-2.5 overflow-x-auto font-mono">
                      {result.sql}
                    </pre>
                  )}
                  {result.retrieved_schema_chunks && (
                    <div>
                      retrieved schema: {result.retrieved_schema_chunks.join(", ")}
                    </div>
                  )}
                </div>
              </details>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
