"use client";

import { useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import Chart from "@/components/Chart";
import FilmStrip from "@/components/FilmStrip";
import GenreShowcase from "@/components/GenreShowcase";
import HeroPreview from "@/components/HeroPreview";
import Markdown from "@/components/Markdown";
import MeetLudo from "@/components/MeetLudo";
import TraceSteps from "@/components/TraceSteps";
import {
  streamAsk,
  type AskResult,
  type ForecastResult,
  type StatsResult,
  type StreamEvent,
} from "@/lib/api";

const EXAMPLE_QUESTIONS = [
  "What are the 5 highest rated games with more than 1000 positive reviews?",
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

function Pill({ children, tone = "muted" }: { children: React.ReactNode; tone?: "muted" | "accent" }) {
  return (
    <span
      className="inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-medium"
      style={
        tone === "accent"
          ? { color: "var(--accent)", background: "color-mix(in srgb, var(--accent) 14%, transparent)" }
          : { color: "var(--muted)", background: "var(--surface-raised)" }
      }
    >
      {children}
    </span>
  );
}

function RouteBadge({ route }: { route: string | null }) {
  if (!route) return null;
  return <Pill tone="accent">{ROUTE_LABELS[route] ?? route}</Pill>;
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
      <div className="text-sm space-y-1 font-mono">
        <div>
          <span className="font-semibold">{s.group_a}</span> mean: {s.mean_a.toFixed(2)}
          {"  ·  "}
          <span className="font-semibold">{s.group_b}</span> mean: {s.mean_b.toFixed(2)}
        </div>
        <div>
          p-value: {s.p_value.toFixed(4)}{" "}
          <span
            className={
              s["significant_at_0.05"]
                ? "text-emerald-400"
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
      <div className="text-sm font-mono">
        <div className="text-[var(--muted)] mb-1">
          outliers beyond z = {s.z_threshold}:
        </div>
        <ul className="space-y-0.5">
          {s.outliers.map((o) => (
            <li key={o.label}>
              <span className="font-semibold">{o.label}</span>: {o.value.toLocaleString()}{" "}
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

function ForecastResultView({ forecast }: { forecast: ForecastResult }) {
  if (forecast.insufficient_history) {
    return (
      <div className="rounded-lg border border-dashed border-[var(--border-strong)] px-3.5 py-3 text-sm">
        <div className="text-[11px] uppercase tracking-wide font-medium text-[var(--muted)] mb-2">
          Insufficient history
        </div>
        <span className="text-[var(--foreground)]">{forecast.message}</span>
      </div>
    );
  }
  return (
    <div className="rounded-lg border border-[var(--border)] px-3.5 py-3 space-y-2">
      <div className="flex items-baseline justify-between flex-wrap gap-2">
        <span className="text-[11px] uppercase tracking-wide font-medium text-[var(--muted)]">
          Projection
        </span>
        {forecast.low_confidence && <Pill>Low confidence</Pill>}
      </div>
      <div className="text-2xl font-semibold font-mono" style={{ color: "var(--accent)" }}>
        ≈ {Math.round(forecast.projected_value ?? 0).toLocaleString()} players
      </div>
      <div className="text-xs font-mono text-[var(--muted)]">
        projected for {forecast.projected_date?.slice(0, 10)} · {forecast.horizon_days}d out ·
        {" "}
        based on {forecast.n_snapshots} snapshot{forecast.n_snapshots === 1 ? "" : "s"} spanning{" "}
        {forecast.observed_span_days?.toFixed(2)}d · R²={forecast.r_squared}
      </div>
      {forecast.low_confidence_reasons && forecast.low_confidence_reasons.length > 0 && (
        <ul className="text-xs font-mono text-[var(--danger)] list-disc list-inside">
          {forecast.low_confidence_reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ResultTable({ columns, rows }: { columns: string[]; rows: unknown[][] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
      <table className="text-sm border-collapse w-full">
        <thead>
          <tr className="border-b border-[var(--border)]">
            {columns.map((c) => (
              <th
                key={c}
                className="text-left py-2 px-3 text-[11px] uppercase tracking-wide font-medium text-[var(--muted)]"
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--border)]">
          {rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td key={j} className="py-2 px-3 font-mono">
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
    <div className="min-h-screen font-sans">
      {/* Hero: headline first, then the film strip of real catalog covers
          as its own framed visual band right below it. */}
      <section className="relative border-b border-[var(--border)]">
        <div className="relative max-w-2xl mx-auto px-6 pt-20 pb-10 text-center">
          <motion.p
            initial="hidden"
            animate="show"
            variants={heroItem}
            className="font-mono text-[11px] tracking-wide uppercase text-[var(--muted)] mb-5"
          >
            AI for the game market
          </motion.p>
          <motion.h1
            initial="hidden"
            animate="show"
            variants={heroItem}
            className="text-6xl sm:text-7xl font-light tracking-tight leading-[0.98] mb-4 text-balance"
          >
            Ask <span style={{ color: "var(--accent)" }}>Ludo</span> a question.
          </motion.h1>
          <motion.p
            initial="hidden"
            animate="show"
            variants={heroItem}
            className="italic text-sm text-[var(--muted)] mb-5"
          >
            Ludo comes from the Latin <em>ludus</em>. Game, play.
          </motion.p>
          <motion.p
            initial="hidden"
            animate="show"
            variants={heroItem}
            transition={{ delay: 0.1 }}
            className="text-[var(--muted)] text-base leading-relaxed max-w-md mx-auto"
          >
            A tool using agent that writes real SQL, runs real statistics, and projects real
            trends against a self collected game market dataset. No guessing, no canned answers.
          </motion.p>
        </div>
        <motion.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1], delay: 0.15 }}
          className="max-w-4xl mx-auto px-6 pb-16"
        >
          <FilmStrip />
        </motion.div>
      </section>

      <div className="max-w-2xl mx-auto px-6 py-14">
        <div className="mb-10">
          <HeroPreview />
        </div>

        <motion.form
          initial="hidden"
          animate="show"
          variants={heroItem}
          onSubmit={(e) => {
            e.preventDefault();
            ask(question);
          }}
          className="mb-3"
        >
          <div className="panel flex items-center gap-2 rounded-lg px-3 py-1 transition-colors focus-within:border-[var(--border-strong)]">
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Ask about the games catalog…"
              className="flex-1 bg-transparent px-1 py-2.5 text-sm outline-none placeholder:text-[var(--muted)]"
            />
            <motion.button
              type="submit"
              disabled={loading || !question.trim()}
              whileHover={loading || !question.trim() ? undefined : { scale: 1.03 }}
              whileTap={loading || !question.trim() ? undefined : { scale: 0.97 }}
              transition={{ duration: 0.15, ease: "easeOut" }}
              className="rounded-md px-4 py-2 text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed"
              style={{ background: "var(--accent)", color: "var(--accent-contrast)" }}
            >
              {loading ? "Asking…" : "Ask"}
            </motion.button>
          </div>
        </motion.form>

        <motion.div initial="hidden" animate="show" variants={heroItem} className="flex flex-wrap gap-1.5">
          {EXAMPLE_QUESTIONS.map((q) => (
            <motion.button
              key={q}
              onClick={() => ask(q)}
              disabled={loading}
              whileHover={loading ? undefined : { y: -1 }}
              whileTap={loading ? undefined : { scale: 0.97 }}
              transition={{ duration: 0.15, ease: "easeOut" }}
              className="rounded-full text-xs px-3 py-1.5 border border-[var(--border)] text-[var(--muted)] hover:border-[var(--border-strong)] hover:text-[var(--foreground)] disabled:opacity-40 transition-colors"
            >
              {q}
            </motion.button>
          ))}
        </motion.div>
      </div>

      <MeetLudo onPick={ask} disabled={loading} />

      <div className="max-w-2xl mx-auto px-6 py-14">
        <div className="mb-12">
          <GenreShowcase onPick={ask} disabled={loading} />
        </div>

        <AnimatePresence mode="wait">
          {(loading || progress.length > 0) && !result && (
            <motion.div
              key="progress"
              initial={{ opacity: 0, filter: "blur(4px)" }}
              animate={{ opacity: 1, filter: "blur(0px)" }}
              exit={{ opacity: 0, filter: "blur(4px)" }}
              transition={{ duration: 0.25, ease: "easeOut" }}
              className="panel mb-6 rounded-xl px-4 py-4"
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
              initial={{ opacity: 0, y: 12, filter: "blur(4px)" }}
              animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
              exit={{ opacity: 0, filter: "blur(4px)" }}
              transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
              className="panel rounded-xl p-5 space-y-4"
            >
              <div className="flex items-center gap-2 flex-wrap">
                <RouteBadge route={result.route} />
                {result.cached && <Pill>Cached</Pill>}
              </div>

              <Markdown>{result.answer}</Markdown>

              {result.forecast_result && <ForecastResultView forecast={result.forecast_result} />}

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
                      <pre className="whitespace-pre-wrap rounded-lg border border-[var(--border)] bg-[var(--background)] p-2.5 overflow-x-auto font-mono">
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
    </div>
  );
}
