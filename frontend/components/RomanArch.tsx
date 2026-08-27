// The hero's one architectural gesture: a single faint arch-and-flutes
// line drawing, not a Colosseum photo or a statue render. The brief this
// direction comes from is explicit that the Roman identity should read as
// "architectural texture," not a hero photograph, and warns directly
// against anything that reads as a history/museum site — a hand-drawn
// outline at very low opacity is the restrained end of that instruction,
// and it keeps this project's standing discipline of never sourcing
// external image/model assets intact (see HeroScene.tsx, GamingObjectsScene
// before it was removed, GradientBlobs before it was removed — every
// visual element in this app has been hand-authored code, not a fetched
// asset, since Slice 9g).
export default function RomanArch({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 420 480"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.4"
      aria-hidden="true"
    >
      {/* the arch */}
      <path d="M40 480 V 220 A 170 170 0 0 1 380 220 V 480" />
      {/* two flanking pilasters */}
      <path d="M40 480 V 200" />
      <path d="M380 480 V 200" />
      {/* faint column flutes inside the arch */}
      <path d="M100 480 V 260" strokeWidth="0.8" opacity="0.6" />
      <path d="M150 480 V 235" strokeWidth="0.8" opacity="0.6" />
      <path d="M210 480 V 222" strokeWidth="0.8" opacity="0.6" />
      <path d="M270 480 V 235" strokeWidth="0.8" opacity="0.6" />
      <path d="M320 480 V 260" strokeWidth="0.8" opacity="0.6" />
    </svg>
  );
}
