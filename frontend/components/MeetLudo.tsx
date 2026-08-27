"use client";

import { motion } from "motion/react";
import GradientBlobs from "@/components/GradientBlobs";

const NEW_CAPABILITY_QUESTIONS = [
  "What are the highest Metacritic-scored games released in 2023?",
  "Which free-to-play games support online co-op?",
  "What's the average price of games with a Metacritic score above 90?",
  "Which games support Linux and have Steam Workshop support?",
];

const container = {
  hidden: {},
  show: { transition: { staggerChildren: 0.06 } },
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
    <section className="relative overflow-hidden py-24">
      <GradientBlobs />

      <motion.div
        variants={container}
        initial="hidden"
        whileInView="show"
        viewport={{ once: true, margin: "-80px" }}
        className="relative max-w-2xl mx-auto px-6 text-center"
      >
        <motion.h2 variants={item} className="text-2xl sm:text-3xl font-semibold tracking-tight mb-3 text-balance">
          What can you ask Ludo?
        </motion.h2>
        <motion.p variants={item} className="text-[var(--muted)] text-base leading-relaxed mb-8">
          Ludo reads a 1,000-game catalog collected from SteamSpy and
          Steam&apos;s own storefront — reviews, price, ownership, playtime,
          release date, Metacritic score, platforms, and feature tags — and
          answers by writing real SQL and running real statistics, not by
          guessing.
        </motion.p>
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
