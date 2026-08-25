import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// The agent's answer is plain LLM prose with inline markdown (bold, bullet
// lists, and — for multi-metric results — real GFM tables, per the system
// prompt's formatting rule added after a table-shaped answer came out as
// raw "* **label:** value * **label:** value" text; see DOCEXP.md) —
// react-markdown handles it properly instead of showing that raw syntax,
// which is what a bare <p> did. `remark-gfm` adds table/strikethrough
// support on top of base CommonMark (bold/lists alone don't need it).
// Styled via the `components` map (explicit per-element styling) rather
// than a global "prose" class, so every element's look is a deliberate
// choice tied to this app's tokens, not inherited from a typography plugin.
export default function Markdown({ children }: { children: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
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
            <span className="text-[var(--accent)] leading-relaxed">–</span>
            <span className="flex-1">{children}</span>
          </li>
        ),
        code: ({ children }) => (
          <code className="font-mono text-xs px-1 py-0.5 rounded border border-[var(--border)] bg-[var(--background)]">
            {children}
          </code>
        ),
        hr: () => <hr className="my-3 border-t border-[var(--border)]" />,
        table: ({ children }) => (
          <div className="my-2.5 overflow-x-auto rounded-lg border border-[var(--border)]">
            <table className="w-full text-xs sm:text-sm font-mono border-collapse">{children}</table>
          </div>
        ),
        thead: ({ children }) => <thead>{children}</thead>,
        tbody: ({ children }) => (
          <tbody className="divide-y divide-[var(--border)]">{children}</tbody>
        ),
        tr: ({ children }) => <tr>{children}</tr>,
        th: ({ children }) => (
          <th
            className="text-left text-[11px] uppercase tracking-wide font-medium px-2.5 py-2 border-b"
            style={{ color: "var(--muted)", borderColor: "var(--border)" }}
          >
            {children}
          </th>
        ),
        td: ({ children }) => <td className="px-2.5 py-1.5 align-top">{children}</td>,
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
