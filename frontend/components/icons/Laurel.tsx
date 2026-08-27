// A single hand-drawn laurel sprig, used in mirrored pairs flanking small
// eyebrow labels (see the hero). Deliberately just a stem + a few leaf
// ticks — a literal wreath or anything more detailed reads as a history-
// museum crest, which the whole point of this motif is to avoid. `flip`
// mirrors it for the right-hand side of a pair.
export default function Laurel({ className, flip = false }: { className?: string; flip?: boolean }) {
  return (
    <svg
      viewBox="0 0 28 14"
      className={className}
      style={flip ? { transform: "scaleX(-1)" } : undefined}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.1"
      strokeLinecap="round"
      aria-hidden="true"
    >
      <path d="M1 12 C 9 12, 18 9, 26 2" />
      <path d="M6 11.3 L 3.6 8.6" />
      <path d="M10.5 10 L 8.4 6.9" />
      <path d="M15 8.2 L 13.3 4.9" />
      <path d="M19.3 6 L 18 2.8" />
      <path d="M23.2 3.6 L 22.4 1" />
    </svg>
  );
}
