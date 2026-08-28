"use client";

import { motion } from "motion/react";

// Slice 15's capabilities row: plain, monochrome, no icon-in-a-colored-
// circle treatment (that colored-chip look died with the site's one
// accent color). Three real capabilities, mapped to the actual agent
// graph in ARCHITECTURE.md (router, retrieve_schema, agent, execute_tools),
// not a fourth invented one just to round out a template.
const ICON_PROPS = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.5,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

function AskIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" {...ICON_PROPS}>
      <path d="M4 5h16v11H8l-4 4z" />
    </svg>
  );
}
function InvestigateIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" {...ICON_PROPS}>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="M19.5 19.5l-4.3-4.3" />
    </svg>
  );
}
function ShowWorkIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" {...ICON_PROPS}>
      <path d="M9 4h6l4 4v12H5V4z" />
      <path d="M9 11h6M9 15h6" />
    </svg>
  );
}

const CAPABILITIES = [
  {
    Icon: AskIcon,
    title: "Ask",
    text: "Ask a plain English question about the game market. No query language to learn.",
  },
  {
    Icon: InvestigateIcon,
    title: "Investigate",
    text: "Ludo classifies the question, retrieves the relevant schema, and writes real SQL or statistics against the catalog.",
  },
  {
    Icon: ShowWorkIcon,
    title: "Show the work",
    text: "Every answer comes with the exact SQL that ran and the rows it returned. Never a number without its source.",
  },
];

const NEW_CAPABILITY_QUESTIONS = [
  "What are the highest Metacritic scored games released in 2023?",
  "Which free to play games support online co-op?",
  "What's the average price of games with a Metacritic score above 90?",
  "Which games support Linux and have Steam Workshop support?",
];

const container = {
  hidden: {},
  show: { transition: { staggerChildren: 0.08 } },
};
const item = {
  hidden: { opacity: 0, y: 12 },
  show: { opacity: 1, y: 0, transition: { duration: 0.5, ease: [0.16, 1, 0.3, 1] as const } },
};

export default function MeetLudo({
  onPick,
  disabled,
}: {
  onPick: (question: string) => void;
  disabled: boolean;
}) {
  return (
    <section className="py-24 border-y border-[var(--border)]">
      <motion.div
        variants={container}
        initial="hidden"
        whileInView="show"
        viewport={{ once: true, margin: "-80px" }}
        className="max-w-5xl mx-auto px-6"
      >
        <motion.div variants={item} className="text-center max-w-2xl mx-auto mb-14">
          <h2 className="text-3xl sm:text-4xl font-semibold tracking-tight mb-3 text-balance">
            What can you ask Ludo?
          </h2>
          <p className="text-[var(--muted)] text-base leading-relaxed">
            Ludo reads a 1,000 game catalog collected from SteamSpy and Steam&apos;s own
            storefront. Reviews, price, ownership, playtime, release date, Metacritic score,
            platforms, and feature tags.
          </p>
        </motion.div>

        <motion.div
          variants={item}
          className="grid sm:grid-cols-3 divide-y sm:divide-y-0 sm:divide-x divide-[var(--border)] mb-14"
        >
          {CAPABILITIES.map(({ Icon, title, text }) => (
            <div key={title} className="px-0 sm:px-8 py-6 sm:py-0 first:pt-0 sm:first:pl-0 last:pl-8">
              <div className="text-[var(--accent)] mb-3">
                <Icon />
              </div>
              <h3 className="font-medium text-sm mb-1.5">{title}</h3>
              <p className="text-sm text-[var(--muted)] leading-relaxed">{text}</p>
            </div>
          ))}
        </motion.div>

        <motion.div variants={item} className="flex flex-wrap justify-center gap-1.5">
          {NEW_CAPABILITY_QUESTIONS.map((q) => (
            <motion.button
              key={q}
              onClick={() => onPick(q)}
              disabled={disabled}
              whileHover={disabled ? undefined : { y: -1 }}
              whileTap={disabled ? undefined : { scale: 0.97 }}
              transition={{ duration: 0.15, ease: "easeOut" }}
              className="rounded-full text-xs px-3 py-1.5 border border-[var(--border)] text-[var(--muted)] hover:border-[var(--border-strong)] hover:text-[var(--foreground)] disabled:opacity-40 transition-colors"
            >
              {q}
            </motion.button>
          ))}
        </motion.div>
      </motion.div>
    </section>
  );
}
