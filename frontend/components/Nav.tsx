"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import Medallion from "@/components/icons/Medallion";

// One shared nav for the whole app (rendered once, in app/layout.tsx) —
// just a wordmark and the two real destinations (ask Ludo / browse the
// catalog). Sticky with a translucent backdrop-blur ground (Slice 13's
// "floating nav" treatment) rather than a scroll-triggered opacity swap —
// simpler to get right and reads just as "floating" without a scroll
// listener. Client-only for usePathname so the current page's link can
// read as active; everything else here is static.
const LINKS = [
  { href: "/", label: "Ask Ludo" },
  { href: "/catalog", label: "Catalog" },
];

export default function Nav() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-50 border-b border-[var(--border)] bg-[var(--background)]/80 backdrop-blur-md">
      <nav className="max-w-5xl mx-auto px-6 h-14 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2 font-medium text-sm tracking-tight">
          <Medallion className="h-4 w-4 text-[var(--accent)]" />
          Ludo
        </Link>
        <div className="flex items-center gap-6">
          {LINKS.map((link) => {
            const active = pathname === link.href;
            return (
              <Link
                key={link.href}
                href={link.href}
                className="text-sm transition-colors"
                style={{ color: active ? "var(--foreground)" : "var(--muted)" }}
              >
                {link.label}
              </Link>
            );
          })}
        </div>
      </nav>
    </header>
  );
}
