import type { Metadata } from "next";
import { IBM_Plex_Mono, Rajdhani } from "next/font/google";
import MotionProvider from "@/components/MotionProvider";
import Nav from "@/components/Nav";
import "./globals.css";

// Two faces:
//   - Rajdhani (Slice 17, replacing Geist directly on request for
//     "professional but also gamer like"): a squarish, technical sans
//     with real esports/gaming-HUD lineage, but clean enough weights
//     (400/500/600) to stay legible as body copy, not just a headline
//     flourish. Carries the whole UI range, same "one sans face, no
//     second display font" discipline Slice 15 settled on.
//   - IBM Plex Mono: data/code readouts (SQL, stats, trace labels, the
//     catalog table). Same face ARCHITECTURE.md's agent-trace artifact
//     already uses, the one thread of typographic continuity kept
//     through every visual rebuild this project has gone through.
const rajdhani = Rajdhani({
  variable: "--font-display",
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
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
    <html lang="en" className={`${rajdhani.variable} ${plexMono.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col">
        <MotionProvider>
          <Nav />
          {children}
        </MotionProvider>
      </body>
    </html>
  );
}
