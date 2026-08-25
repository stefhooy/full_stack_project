// Hand-authored line-art glyphs, one per genre in lib/genres.ts — no icon
// library. Each is a plain 24x24 stroke drawing in currentColor so it
// inherits whatever color the caller sets (usually a --genre-N token), and
// carries its own <title> so genre identity never rests on color alone even
// before the text label next to it is considered.

const SHARED = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.9,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

function Action() {
  return (
    <>
      <circle cx="12" cy="12" r="7.5" {...SHARED} />
      <circle cx="12" cy="12" r="2.4" {...SHARED} />
      <path d="M12 3.2v3M12 17.8v3M3.2 12h3M17.8 12h3" {...SHARED} />
    </>
  );
}

function Adventure() {
  return (
    <>
      <circle cx="12" cy="12" r="8" {...SHARED} />
      <path d="M15.2 8.8 13 13l-4.2 2.2L11 11z" {...SHARED} strokeLinejoin="round" />
    </>
  );
}

function Indie() {
  return (
    <path
      d="M12 19.5s-6.8-4.15-6.8-9.1A3.9 3.9 0 0 1 12 7.9a3.9 3.9 0 0 1 6.8 2.5c0 4.95-6.8 9.1-6.8 9.1Z"
      {...SHARED}
    />
  );
}

function RPG() {
  return (
    <>
      <path d="M12 3.5 20 8v8l-8 4.5L4 16V8Z" {...SHARED} />
      <path d="M4 8l8 4.5 8-4.5M12 12.5v8" {...SHARED} />
    </>
  );
}

function Simulation() {
  return (
    <>
      <circle cx="12" cy="12" r="3" {...SHARED} />
      <path
        d="M12 4.6v2.3M12 17.1v2.3M19.4 12h-2.3M6.9 12H4.6M17.4 6.6l-1.6 1.6M8.2 15.8l-1.6 1.6M17.4 17.4l-1.6-1.6M8.2 8.2 6.6 6.6"
        {...SHARED}
      />
    </>
  );
}

function MMO() {
  return (
    <>
      <circle cx="6" cy="7" r="2.1" {...SHARED} />
      <circle cx="18" cy="7" r="2.1" {...SHARED} />
      <circle cx="12" cy="17.5" r="2.1" {...SHARED} />
      <path d="M7.6 8.4 10.6 16M16.4 8.4 13.4 16M8.1 7h7.8" {...SHARED} />
    </>
  );
}

function Strategy() {
  return (
    <>
      <rect x="4" y="4" width="16" height="16" rx="1.5" {...SHARED} />
      <path d="M4 9.3h16M4 14.7h16M9.3 4v16M14.7 4v16" {...SHARED} strokeWidth={1.2} />
    </>
  );
}

function Casual() {
  return (
    <>
      <rect x="4.5" y="4.5" width="15" height="15" rx="5" {...SHARED} />
      <path d="M9 10.2h.01M15 10.2h.01" {...SHARED} strokeWidth={2.4} />
      <path d="M8.7 14.3c.9 1.15 2 1.75 3.3 1.75s2.4-.6 3.3-1.75" {...SHARED} />
    </>
  );
}

function Sports() {
  return (
    <>
      <circle cx="12" cy="12" r="8" {...SHARED} />
      <path
        d="M12 4v16M4.6 8.5h14.8M4.6 15.5h14.8M12 4a11 11 0 0 1 0 16 11 11 0 0 1 0-16Z"
        {...SHARED}
      />
    </>
  );
}

function Racing() {
  return (
    <>
      <path d="M5 4v16" {...SHARED} />
      <path
        d="M5 4h6.5l-1.5 2.5L13 9H5.5"
        {...SHARED}
        strokeLinejoin="round"
      />
      <path d="M5 9h5l1.5 2.5L10 14H5" {...SHARED} strokeLinejoin="round" />
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
      <rect x="3.5" y="8.5" width="17" height="9" rx="4.5" {...SHARED} />
      <path d="M8 11v4M6 13h4" {...SHARED} />
      <path d="M15.2 12.3h.01M17.6 14.3h.01" {...SHARED} strokeWidth={2.4} />
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
