"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// One shared nav for the whole app (rendered once, in app/layout.tsx) —
// just a wordmark and the two real destinations (ask Ludo / browse the
// catalog). Client-only for usePathname so the current page's link can
// read as active; everything else here is static.
const LINKS = [
  { href: "/", label: "Ask Ludo" },
  { href: "/catalog", label: "Catalog" },
];

export default function Nav() {
  const pathname = usePathname();

  return (
    <header className="border-b border-[var(--border)]">
      <nav className="max-w-5xl mx-auto px-6 h-14 flex items-center justify-between">
        <Link href="/" className="font-mono text-sm font-medium tracking-tight">
          Ludo
        </Link>
        <div className="flex items-center gap-5">
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
