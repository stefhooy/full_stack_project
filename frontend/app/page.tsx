"use client";

import { useRef, useState } from "react";
import Chart from "@/components/Chart";
import { streamAsk, type AskResult, type StatsResult } from "@/lib/api";

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
    <span className="inline-flex items-center rounded-full border border-black/10 dark:border-white/15 px-2.5 py-0.5 text-xs font-medium text-neutral-600 dark:text-neutral-300">
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
                : "text-neutral-500"
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
        <div className="text-neutral-500 mb-1">
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
    <div className="text-sm">
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
          <tr className="border-b border-black/10 dark:border-white/15">
            {columns.map((c) => (
              <th key={c} className="text-left py-1.5 pr-4 font-medium text-neutral-500">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-black/5 dark:border-white/5">
              {row.map((cell, j) => (
                <td key={j} className="py-1.5 pr-4">
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

export default function Home() {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [progress, setProgress] = useState<string[]>([]);
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
            setProgress((prev) => [...prev, event.message]);
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

  return (
    <div className="min-h-screen font-sans max-w-2xl mx-auto px-6 py-12">
      <h1 className="text-2xl font-semibold mb-1">AI Game Analyst</h1>
      <p className="text-neutral-500 text-sm mb-6">
        Ask a plain-English question about the video game market. The agent writes
        real SQL, runs real statistics, and shows its work.
      </p>

      <div className="flex flex-wrap gap-2 mb-4">
        {EXAMPLE_QUESTIONS.map((q) => (
          <button
            key={q}
            onClick={() => ask(q)}
            disabled={loading}
            className="text-xs px-3 py-1.5 rounded-full border border-black/10 dark:border-white/15 text-neutral-700 dark:text-neutral-200 hover:bg-black/5 dark:hover:bg-white/10 disabled:opacity-40 transition-colors"
          >
            {q}
          </button>
        ))}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          ask(question);
        }}
        className="flex gap-2 mb-6"
      >
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask about the games catalog..."
          className="flex-1 rounded-lg border border-black/10 dark:border-white/15 bg-transparent px-3 py-2 text-sm outline-none focus:border-black/30 dark:focus:border-white/30"
        />
        <button
          type="submit"
          disabled={loading || !question.trim()}
          className="rounded-lg bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 px-4 py-2 text-sm font-medium disabled:opacity-40"
        >
          {loading ? "..." : "Ask"}
        </button>
      </form>

      {progress.length > 0 && (
        <div className="text-xs text-neutral-500 mb-4 space-y-0.5">
          {progress.map((p, i) => (
            <div key={i} className={i === progress.length - 1 && loading ? "font-medium" : ""}>
              {p}
            </div>
          ))}
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-red-200 dark:border-red-900/50 bg-red-50 dark:bg-red-950/30 text-red-700 dark:text-red-300 text-sm px-4 py-3 mb-4">
          {error}
        </div>
      )}

      {result && (
        <div className="rounded-lg border border-black/10 dark:border-white/15 p-4 space-y-4">
          <div className="flex items-center gap-2 flex-wrap">
            <RouteBadge route={result.route} />
            {result.cached && (
              <span className="inline-flex items-center rounded-full border border-black/10 dark:border-white/15 px-2.5 py-0.5 text-xs font-medium text-neutral-500">
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
            <details className="text-xs text-neutral-500">
              <summary className="cursor-pointer select-none">Show the work</summary>
              <div className="mt-2 space-y-2">
                {result.sql && (
                  <pre className="whitespace-pre-wrap rounded bg-black/5 dark:bg-white/5 p-2 overflow-x-auto">
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
        </div>
      )}
    </div>
  );
}
