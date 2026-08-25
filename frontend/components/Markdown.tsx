import ReactMarkdown from "react-markdown";

// The agent's answer is plain LLM prose with inline markdown (bold, bullet
// lists mainly) — react-markdown handles it properly instead of the raw
// `**text**`/`* item` showing up literally, which is what a bare <p> did.
// Styled via the `components` map (explicit per-element styling) rather
// than a global "prose" class, so every element's look is a deliberate
// choice tied to this app's tokens, not inherited from a typography plugin.
export default function Markdown({ children }: { children: string }) {
  return (
    <ReactMarkdown
      components={{
        p: ({ children }) => (
          <p className="text-sm leading-relaxed mb-2 last:mb-0">{children}</p>
        ),
        strong: ({ children }) => (
          <strong className="font-semibold" style={{ color: "var(--accent)" }}>
            {children}
          </strong>
        ),
        em: ({ children }) => <em>{children}</em>,
        ul: ({ children }) => (
          <ul className="text-sm leading-relaxed space-y-1 my-2 pl-1">{children}</ul>
        ),
        ol: ({ children }) => (
          <ol className="text-sm leading-relaxed space-y-1 my-2 pl-4 list-decimal">
            {children}
          </ol>
        ),
        li: ({ children }) => (
          <li className="flex gap-2">
            <span className="font-pixel text-[6px] mt-1.5" style={{ color: "var(--accent)" }}>
              ▸
            </span>
            <span className="flex-1">{children}</span>
          </li>
        ),
        code: ({ children }) => (
          <code className="font-mono text-xs px-1 py-0.5 border border-[var(--border)] bg-[var(--background)]">
            {children}
          </code>
        ),
        a: ({ children, href }) => (
          <a
            href={href}
            target="_blank"
            rel="noreferrer"
            className="underline underline-offset-2"
            style={{ color: "var(--accent)" }}
          >
            {children}
          </a>
        ),
      }}
    >
      {children}
    </ReactMarkdown>
  );
}
