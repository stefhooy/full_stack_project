// Nav logomark: an abstract classical medallion (a ring, a center mark,
// four short ticks at the cardinal points) rather than a literal coin,
// shield, or laurel wreath crest — the brief's own guidance ("keep it
// extremely simple") plus this project's standing rule against literal
// iconography (see HeroScene.tsx's reasoning for abstract genre shapes,
// not literal dice/controllers).
export default function Medallion({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.3"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="8.5" />
      <circle cx="12" cy="12" r="2" fill="currentColor" stroke="none" />
      <path d="M12 1.5v2.4M12 20.1v2.4M1.5 12h2.4M20.1 12h2.4" strokeLinecap="round" />
    </svg>
  );
}
