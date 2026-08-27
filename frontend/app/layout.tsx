import type { Metadata } from "next";
import { Geist, IBM_Plex_Mono, Instrument_Serif } from "next/font/google";
import MotionProvider from "@/components/MotionProvider";
import Nav from "@/components/Nav";
import "./globals.css";

// Three faces, each with one job (Slice 13's "Roman Intelligence" re-skin
// added the serif; Geist/Plex Mono are unchanged from Slice 9g) —
// restraint over decoration:
//   - Instrument Serif: display headlines only (h1/h2-scale). The
//     "classical intelligence" half of the brief's own "ancient structure,
//     modern intelligence" tension — an editorial serif, not a novelty
//     display face, used exactly where a headline needs weight and
//     nowhere else (never body copy, never UI chrome).
//   - Geist: UI/body copy. Real typographic hierarchy (weight + size)
//     still does the work everywhere that isn't a headline — Vercel's own
//     font, genuinely associated with serious dev tooling.
//   - IBM Plex Mono: data/code readouts (SQL, stats, trace labels). Same
//     face ARCHITECTURE.md's agent-trace artifact already uses — the one
//     thread of typographic continuity kept through every visual rebuild
//     this project has gone through.
const geist = Geist({
  variable: "--font-display",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

const instrumentSerif = Instrument_Serif({
  variable: "--font-serif-display",
  subsets: ["latin"],
  weight: ["400"],
  style: ["normal", "italic"],
});

const plexMono = IBM_Plex_Mono({
  variable: "--font-data-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: "AI Game Analyst",
  description:
    "Ask plain-English questions about the video game market. A tool-using AI agent writes real SQL, runs real statistics, and shows its work.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geist.variable} ${instrumentSerif.variable} ${plexMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <MotionProvider>
          <Nav />
          {children}
        </MotionProvider>
      </body>
    </html>
  );
}
