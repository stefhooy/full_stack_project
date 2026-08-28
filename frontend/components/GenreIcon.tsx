// Hand-authored line-art glyphs, one per genre in lib/genres.ts — no icon
// library. Redrawn for Slice 16 (direct feedback: "change the icons... I
// don't like them") with a thin engraved-medallion ring built into every
// glyph — a restrained nod to a Roman coin/seal, the one small "Latin
// touch" applied here rather than reviving the deleted full Roman
// identity. Each is a plain 24x24 stroke drawing in currentColor so it
// inherits whatever color the caller sets (usually a --genre-N token), and
// carries its own <title> so genre identity never rests on color alone
// even before the text label next to it is considered.

const SHARED = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

// The medallion ring every glyph sits inside, drawn once per icon rather
// than factored into a wrapper element, so it's part of the artwork
// itself (the same "coin" a caller's color tints, not a separate frame).
function Ring() {
  return <circle cx="12" cy="12" r="9.5" {...SHARED} strokeWidth={1.1} opacity={0.55} />;
}

function Action() {
  return (
    <>
      <Ring />
      <circle cx="12" cy="12" r="4.6" {...SHARED} />
      <path d="M12 4.8v2.4M12 16.8v2.4M4.8 12h2.4M16.8 12h2.4" {...SHARED} />
    </>
  );
}

function Adventure() {
  return (
    <>
      <Ring />
      <path d="M12 5.5 8.3 15.2l3.7-2.1 3.7 2.1Z" {...SHARED} strokeLinejoin="round" />
    </>
  );
}

function Indie() {
  return (
    <>
      <Ring />
      <path d="M12 5.5 13.4 10.4 18 12 13.4 13.6 12 18.5 10.6 13.6 6 12 10.6 10.4Z" {...SHARED} strokeLinejoin="round" />
    </>
  );
}

function RPG() {
  return (
    <>
      <Ring />
      <path d="M12 5.2 16.5 7v4.3c0 3.4-2 5.6-4.5 6.9-2.5-1.3-4.5-3.5-4.5-6.9V7Z" {...SHARED} strokeLinejoin="round" />
    </>
  );
}

function Simulation() {
  return (
    <>
      <Ring />
      <circle cx="12" cy="12" r="2.6" {...SHARED} />
      <path
        d="M12 6.3v1.9M12 15.8v1.9M17.7 12h-1.9M8.2 12H6.3M15.9 8.1l-1.3 1.3M9.4 14.5l-1.3 1.3M15.9 15.9l-1.3-1.3M9.4 9.5 8.1 8.2"
        {...SHARED}
      />
    </>
  );
}

function MMO() {
  return (
    <>
      <Ring />
      <circle cx="8.3" cy="9.3" r="1.7" {...SHARED} />
      <circle cx="15.7" cy="9.3" r="1.7" {...SHARED} />
      <circle cx="12" cy="16.2" r="1.7" {...SHARED} />
      <path d="M9.3 10.6 11.2 14.7M14.7 10.6 12.8 14.7M9.9 9.3h4.2" {...SHARED} />
    </>
  );
}

function Strategy() {
  return (
    <>
      <Ring />
      <path d="M12 5.5 17.3 8.4v6.6L12 18.5 6.7 15V8.4Z" {...SHARED} strokeLinejoin="round" />
      <path d="M6.7 8.4 12 11.3l5.3-2.9M12 11.3v7.2" {...SHARED} strokeWidth={1} />
    </>
  );
}

function Casual() {
  return (
    <>
      <Ring />
      <circle cx="9" cy="10.5" r="0.9" {...SHARED} strokeWidth={2.2} />
      <circle cx="15" cy="10.5" r="0.9" {...SHARED} strokeWidth={2.2} />
      <path d="M8.5 14.2c1 1.15 2.1 1.75 3.5 1.75s2.5-.6 3.5-1.75" {...SHARED} />
    </>
  );
}

function Sports() {
  return (
    <>
      <Ring />
      <circle cx="12" cy="12" r="5.5" {...SHARED} />
      <path d="M12 6.5v11M6.5 12h11" {...SHARED} strokeWidth={1.1} />
    </>
  );
}

function Racing() {
  return (
    <>
      <Ring />
      <path d="M7 6.5v11" {...SHARED} />
      <path d="M7 6.5h6l-1.3 2.2L14 11H7.5" {...SHARED} strokeLinejoin="round" />
      <path d="M7 11h4.3l1.3 2.2L11.3 15.4H7" {...SHARED} strokeLinejoin="round" />
    </>
  );
}

// Fallback for any genre this component hasn't been hand-drawn for yet — a
// generic controller glyph rather than silently reusing Action's, so an
// unrecognized genre from the live /genres endpoint (see GenreShowcase.tsx)
// still reads as "a genre, unspecified" instead of implying it's Action.
function Generic() {
  return (
    <>
      <Ring />
      <rect x="6.5" y="9.5" width="11" height="6.5" rx="3" {...SHARED} />
      <path d="M9.3 11.5v2.5M8 12.75h2.5" {...SHARED} strokeWidth={1.2} />
      <path d="M14.3 11.9h.01M15.9 13.3h.01" {...SHARED} strokeWidth={2} />
    </>
  );
}

const ICONS: Record<string, () => ReturnType<typeof Action>> = {
  action: Action,
  adventure: Adventure,
  indie: Indie,
  rpg: RPG,
  simulation: Simulation,
  mmo: MMO,
  strategy: Strategy,
  casual: Casual,
  sports: Sports,
  racing: Racing,
};

export default function GenreIcon({
  genreId,
  label,
  className,
}: {
  genreId: string;
  label: string;
  className?: string;
}) {
  const Glyph = ICONS[genreId] ?? Generic;
  return (
    <svg
      viewBox="0 0 24 24"
      width="22"
      height="22"
      role="img"
      aria-label={`${label} icon`}
      className={className}
    >
      <title>{label}</title>
      <Glyph />
    </svg>
  );
}
