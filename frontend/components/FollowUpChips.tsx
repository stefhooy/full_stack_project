"use client";

// Slice 63: up to 3 deterministic, zero-Groq-cost suggested next
// questions (src/agent/follow_ups.py). Deliberately labeled "Try
// asking" rather than "Continue with" -- each chip is a brand-new,
// self-contained question, not a continuation Ludo is tracking. See
// ARCHITECTURE.md's "Known limitations" section for the one-hop-only
// distinction this framing exists to keep honest.
export default function FollowUpChips({
  suggestions,
  onPick,
  disabled,
}: {
  suggestions: string[];
  onPick: (q: string) => void;
  disabled: boolean;
}) {
  if (suggestions.length === 0) return null;

  return (
    <div className="space-y-1.5">
      <div className="text-xs font-mono uppercase tracking-wide text-[var(--muted)]">
        Try asking
      </div>
      <div className="flex flex-wrap gap-1.5">
        {suggestions.map((q) => (
          <button
            key={q}
            type="button"
            onClick={() => onPick(q)}
            disabled={disabled}
            className="rounded-full text-xs px-3 py-1.5 border border-[var(--border)] text-[var(--muted)] hover:border-[var(--border-strong)] hover:text-[var(--foreground)] disabled:opacity-40 transition-colors"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
