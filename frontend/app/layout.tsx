import type { Metadata } from "next";
import { Geist, IBM_Plex_Mono } from "next/font/google";
import MotionProvider from "@/components/MotionProvider";
import Nav from "@/components/Nav";
import "./globals.css";

// Two faces, back to the simplest version of this system yet (Slice 15
// dropped the serif entirely, along with everything else decorative):
//   - Geist: every piece of UI copy, from the hero headline down to a
//     button label. Vercel's own font, genuinely associated with serious
//     dev tooling, carrying the whole typographic range on its own now
//     that there is no second display face splitting the job.
//   - IBM Plex Mono: data/code readouts (SQL, stats, trace labels, the
//     catalog table). Same face ARCHITECTURE.md's agent-trace artifact
//     already uses, the one thread of typographic continuity kept
//     through every visual rebuild this project has gone through.
const geist = Geist({
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
    <html lang="en" className={`${geist.variable} ${plexMono.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col">
        <MotionProvider>
          <Nav />
          {children}
        </MotionProvider>
      </body>
    </html>
  );
}
