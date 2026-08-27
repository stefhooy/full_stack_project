"use client";

import { motion } from "motion/react";
import Laurel from "@/components/icons/Laurel";

// Slice 13's re-skin replaced the turquoise gradient-blob background
// (Slice 12b) with a plain, spacious capabilities row — closer to what
// the "Roman Intelligence" brief actually asks for here ("prefer a
// horizontal editorial row separated by thin vertical rules," not another
// ambient visual effect) and honest about what's real: three capabilities
// Ludo genuinely has (ARCHITECTURE.md's router → retrieve_schema → agent →
// execute_tools graph), not a fourth invented one just to round out a
// template.
const ICON_PROPS = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
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
    text: "Ask a plain-English question about the game market — no query language to learn.",
  },
  {
    Icon: InvestigateIcon,
    title: "Investigate",
    text: "Ludo classifies the question, retrieves the relevant schema, and writes real SQL or statistics against the catalog.",
  },
  {
    Icon: ShowWorkIcon,
    title: "Show the work",
    text: "Every answer comes with the exact SQL that ran and the rows it returned — never a number without its source.",
  },
];

const NEW_CAPABILITY_QUESTIONS = [
  "What are the highest Metacritic-scored games released in 2023?",
  "Which free-to-play games support online co-op?",
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
    <section className="py-24 border-y border-[var(--border)] bg-[var(--surface)]">
      <motion.div
        variants={container}
        initial="hidden"
        whileInView="show"
        viewport={{ once: true, margin: "-80px" }}
        className="max-w-5xl mx-auto px-6"
      >
        <motion.div variants={item} className="text-center max-w-2xl mx-auto mb-14">
          <h2 className="font-serif text-3xl sm:text-4xl font-normal mb-3 text-balance">
            What can you ask Ludo?
          </h2>
          <p className="text-[var(--muted)] text-base leading-relaxed">
            Ludo reads a 1,000-game catalog collected from SteamSpy and
            Steam&apos;s own storefront — reviews, price, ownership, playtime,
            release date, Metacritic score, platforms, and feature tags.
          </p>
        </motion.div>

        <motion.div
          variants={item}
          className="grid sm:grid-cols-3 divide-y sm:divide-y-0 sm:divide-x divide-[var(--border)] mb-14"
        >
          {CAPABILITIES.map(({ Icon, title, text }) => (
            <div key={title} className="px-0 sm:px-8 py-6 sm:py-0 first:pt-0 sm:first:pl-0 last:pl-8">
              <div
                className="inline-flex h-9 w-9 items-center justify-center rounded-full mb-3"
                style={{ color: "var(--accent)", background: "color-mix(in srgb, var(--accent) 10%, transparent)" }}
              >
                <Icon />
              </div>
              <h3 className="font-medium text-sm mb-1.5">{title}</h3>
              <p className="text-sm text-[var(--muted)] leading-relaxed">{text}</p>
            </div>
          ))}
        </motion.div>

        <motion.div variants={item} className="flex justify-center mb-6 text-[var(--border-strong)]">
          <Laurel className="h-4 w-8" />
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
              className="rounded-full text-xs px-3 py-1.5 border border-[var(--border)] bg-[var(--surface-raised)] text-[var(--muted)] hover:border-[var(--border-strong)] hover:text-[var(--foreground)] disabled:opacity-40 transition-colors"
            >
              {q}
            </motion.button>
          ))}
        </motion.div>
      </motion.div>
    </section>
  );
}
