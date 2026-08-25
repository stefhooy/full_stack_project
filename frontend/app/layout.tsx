import type { Metadata } from "next";
import { Geist, IBM_Plex_Mono } from "next/font/google";
import MotionProvider from "@/components/MotionProvider";
import "./globals.css";

// Two faces, each with one job — restraint over decoration:
//   - Geist: UI/body/headline. Real typographic hierarchy (weight + size)
//     carries the hero instead of a novelty display face — the previous
//     pass's Monoton/Press Start 2P read as the arcade-template signal
//     more than any single other choice, so both are gone, not just toned
//     down. Vercel's own font; genuinely associated with serious dev
//     tooling rather than a generic "safe" default.
//   - IBM Plex Mono: data/code readouts (SQL, stats, trace labels). Same
//     face ARCHITECTURE.md's agent-trace artifact already uses — the one
//     thread of typographic continuity kept through this rebuild.
const geist = Geist({
  variable: "--font-display",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
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
    <html lang="en" className={`${geist.variable} ${plexMono.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col">
        <MotionProvider>{children}</MotionProvider>
      </body>
    </html>
  );
}
