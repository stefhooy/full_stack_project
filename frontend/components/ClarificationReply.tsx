"use client";

import { useState } from "react";

// Slice 63's one-hop follow-up: when Ludo's router genuinely can't tell
// what a question means (route === "needs_clarification" and
// awaiting_reply === true, see src/agent/graph.py), this renders instead
// of a dead end. Deliberately NOT styled like a chat bubble/thread --
// this completes one missing detail in the original question, it isn't
// the start of an ongoing conversation Ludo is tracking. See
// ARCHITECTURE.md's "Known limitations" section for why that distinction
// matters: the UI should never imply more memory than the one-hop reply
// it actually carries.
export default function ClarificationReply({
  onSubmit,
  disabled,
}: {
  onSubmit: (reply: string) => void;
  disabled: boolean;
}) {
  const [reply, setReply] = useState("");

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!reply.trim() || disabled) return;
        onSubmit(reply);
        setReply("");
      }}
      className="space-y-2"
    >
      <div className="text-xs font-mono uppercase tracking-wide text-[var(--muted)]">
        Ludo needs one more detail before it can answer
      </div>
      <div className="glass flex items-center gap-2 rounded-lg px-3 py-1 transition-colors focus-within:border-[var(--border-strong)]">
        <input
          value={reply}
          onChange={(e) => setReply(e.target.value)}
          placeholder="Your answer…"
          autoFocus
          className="flex-1 bg-transparent px-1 py-2.5 text-sm outline-none placeholder:text-[var(--muted)]"
        />
        <button
          type="submit"
          disabled={disabled || !reply.trim()}
          className="shrink-0 rounded-full px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-40"
          style={{ color: "var(--accent-contrast)", background: "var(--accent)" }}
        >
          {disabled ? "Answering…" : "Answer"}
        </button>
      </div>
    </form>
  );
}
