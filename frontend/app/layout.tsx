import type { Metadata } from "next";
import { Chakra_Petch, IBM_Plex_Mono, Monoton, Press_Start_2P } from "next/font/google";
import MotionProvider from "@/components/MotionProvider";
import RetroBackground from "@/components/RetroBackground";
import "./globals.css";

// Four faces, each with one job — an 80s-arcade-cabinet identity, not a
// generic display/body pair:
//   - Chakra Petch: UI/body text. A retro-computer/tech face (squared-off
//     terminals, slightly angular) that still reads cleanly at paragraph
//     size — swapped in for Archivo, which was doing the "readable" job
//     fine but wasn't reading as retro at all next to the other three.
//   - IBM Plex Mono: data/code/HUD readouts. Same pairing as
//     ARCHITECTURE.md's agent-trace artifact, kept for brand continuity.
//   - Monoton: the hero headline ONLY — neon-tube marquee lettering, used
//     in exactly one place (see artifact-design's "spend your boldness in
//     one place" — this is that one place).
//   - Press Start 2P: short pixel-font labels (eyebrows, badges, section
//     headers) — genuinely 8-bit, illegible at paragraph length by design,
//     so it's never used for anything longer than a few words.
const chakraPetch = Chakra_Petch({
  variable: "--font-display",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

const plexMono = IBM_Plex_Mono({
  variable: "--font-data-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});

const monoton = Monoton({
  variable: "--font-marquee",
  subsets: ["latin"],
  weight: "400",
});

const pressStart = Press_Start_2P({
  variable: "--font-pixel",
  subsets: ["latin"],
  weight: "400",
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
      className={`${chakraPetch.variable} ${plexMono.variable} ${monoton.variable} ${pressStart.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <RetroBackground />
        <MotionProvider>{children}</MotionProvider>
      </body>
    </html>
  );
}
