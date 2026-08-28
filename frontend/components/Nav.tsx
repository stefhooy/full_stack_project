"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// One shared nav for the whole app, rendered once in app/layout.tsx.
// Deliberately plain: a text wordmark, two links, nothing else. Slice 15
// dropped the medallion icon along with every other decorative touch;
// restraint in the chrome is what makes the hero's real data field read
// as the one thing worth looking at.
const LINKS = [
  { href: "/", label: "Ask Ludo" },
  { href: "/catalog", label: "Catalog" },
];

export default function Nav() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-50 border-b border-[var(--border)] bg-[var(--background)]/85 backdrop-blur-md">
      <nav className="max-w-5xl mx-auto px-6 h-14 flex items-center justify-between">
        <Link href="/" className="font-medium text-sm tracking-tight">
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
