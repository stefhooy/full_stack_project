// Talks to the FastAPI backend's /ask/stream (SSE) endpoint.
//
// Not using the browser's EventSource for this: EventSource only supports
// GET requests, and the question has to go in a POST body (arbitrary
// length, JSON). So this parses the SSE wire format by hand from a plain
// fetch() ReadableStream — the format is simple (`data: <json>\n\n` per
// event) and doing it directly avoids pulling in an SSE client library for
// something this small.

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

export interface ChartSpec {
  type: "bar" | "scatter";
  x: { field: string };
  y: { field: string };
  data: Record<string, string | number>[];
}

export interface StatsResult {
  mode: "describe" | "compare_two_groups" | "outliers";
  [key: string]: unknown;
}

export interface ForecastResult {
  mode: "forecast";
  insufficient_history: boolean;
  n_snapshots: number;
  earliest_snapshot: string;
  // Present only when insufficient_history is false:
  latest_snapshot?: string;
  observed_span_days?: number;
  horizon_days?: number;
  projected_date?: string;
  projected_value?: number;
  slope_per_day?: number;
  r_squared?: number;
  low_confidence?: boolean;
  low_confidence_reasons?: string[];
  // Present only when insufficient_history is true:
  message?: string;
}

export interface AskResult {
  answer: string;
  sql: string | null;
  columns: string[] | null;
  rows: unknown[][] | null;
  stats_result: StatsResult | null;
  forecast_result: ForecastResult | null;
  chart_spec: ChartSpec | null;
  retrieved_schema_chunks: string[] | null;
  route: string | null;
  cached: boolean;
}

export type StreamEvent =
  | { type: "progress"; node: string; message: string }
  | { type: "final"; result: AskResult }
  | { type: "error"; message: string };

export async function streamAsk(
  question: string,
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/ask/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
    signal,
  });

  if (!response.ok || !response.body) {
    const detail = await response.text().catch(() => "");
    onEvent({
      type: "error",
      message: detail || `Request failed (${response.status})`,
    });
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line; each frame's payload is
    // one or more "data: ..." lines.
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const line = frame.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      const json = line.slice("data: ".length);
      try {
        onEvent(JSON.parse(json) as StreamEvent);
      } catch {
        // Malformed frame (shouldn't happen against our own backend) --
        // skip rather than crash the whole stream over one bad frame.
      }
    }
  }
}
