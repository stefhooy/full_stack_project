"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { motion } from "motion/react";
import { fetchCatalog, type CatalogGame, type CatalogSort } from "@/lib/catalog";
import { fetchGenres, type Genre } from "@/lib/genres";

const PAGE_SIZE = 24;

const SORT_OPTIONS: { value: CatalogSort; label: string }[] = [
  { value: "peak_ccu", label: "Peak players" },
  { value: "metacritic_score", label: "Metacritic score" },
  { value: "review_score", label: "Review score" },
  { value: "release_date", label: "Release date" },
  { value: "price_usd", label: "Price" },
  { value: "owners_high", label: "Owners" },
  { value: "name", label: "Name" },
];

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n % 1_000_000 === 0 ? 0 : 1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n % 1_000 === 0 ? 0 : 1)}K`;
  return String(n);
}

function formatOwners(low: number | null, high: number | null): string {
  if (low == null || high == null) return "—";
  return `${formatCount(low)}–${formatCount(high)}`;
}

function formatPrice(price: number | null): string {
  if (price == null) return "—";
  return price === 0 ? "Free" : `$${price.toFixed(2)}`;
}

function PlatformBadges({ platforms }: { platforms: string | null }) {
  if (!platforms) return <span className="text-[var(--muted)]">—</span>;
  const labels: Record<string, string> = { windows: "Win", mac: "Mac", linux: "Linux" };
  const list = platforms.split(",").map((p) => labels[p.trim()] ?? p.trim());
  return <span>{list.join(" · ")}</span>;
}

function TableSkeleton() {
  return (
    <div className="space-y-1.5">
      {Array.from({ length: 10 }).map((_, i) => (
        <div key={i} className="h-9 rounded bg-[var(--surface-raised)] animate-pulse" />
      ))}
    </div>
  );
}

export default function CatalogClient() {
  const [genres, setGenres] = useState<Genre[] | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [genre, setGenre] = useState("");
  const [sort, setSort] = useState<CatalogSort>("peak_ccu");
  const [order, setOrder] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(1);

  const [games, setGames] = useState<CatalogGame[] | null>(null);
  const [total, setTotal] = useState(0);
  const [failed, setFailed] = useState(false);

  // Debounce the search box -- fires the actual request 300ms after typing
  // stops, not on every keystroke.
  useEffect(() => {
    const t = setTimeout(() => {
      setSearch(searchInput);
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  useEffect(() => {
    const controller = new AbortController();
    fetchGenres(controller.signal)
      .then(setGenres)
      .catch(() => {});
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    fetchCatalog({ q: search, genre, sort, order, page, pageSize: PAGE_SIZE }, controller.signal)
      .then((data) => {
        setGames(data.games);
        setTotal(data.total);
      })
      .catch((e) => {
        if ((e as Error).name !== "AbortError") setFailed(true);
      });
    return () => controller.abort();
  }, [search, genre, sort, order, page]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="min-h-screen font-sans">
      <div className="max-w-7xl mx-auto px-6 pt-10 pb-16">
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
          className="mb-6"
        >
          <h1 className="text-2xl sm:text-3xl font-semibold tracking-tight mb-2 text-balance">
            The full catalog
          </h1>
          <p className="text-[var(--muted)] text-sm">
            {total.toLocaleString()} games, updated as the catalog is re-ingested. For a
            question with an answer, not just a filter,{" "}
            <Link href="/" className="underline underline-offset-2 hover:text-[var(--foreground)]">
              ask Ludo
            </Link>{" "}
            instead.
          </p>
        </motion.div>

        <div className="flex flex-wrap gap-2 mb-4">
          <input
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search by name…"
            className="panel rounded-lg px-3 py-2 text-sm outline-none placeholder:text-[var(--muted)] flex-1 min-w-[180px] focus:border-[var(--border-strong)]"
          />
          <select
            value={genre}
            onChange={(e) => {
              setGenre(e.target.value);
              setPage(1);
            }}
            className="panel rounded-lg px-3 py-2 text-sm outline-none"
          >
            <option value="">All genres</option>
            {genres?.map((g) => (
              <option key={g.label} value={g.label}>
                {g.label}
              </option>
            ))}
          </select>
          <select
            value={sort}
            onChange={(e) => {
              setSort(e.target.value as CatalogSort);
              setPage(1);
            }}
            className="panel rounded-lg px-3 py-2 text-sm outline-none"
          >
            {SORT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                Sort: {o.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => setOrder(order === "asc" ? "desc" : "asc")}
            className="panel rounded-lg px-3 py-2 text-sm text-[var(--muted)] hover:text-[var(--foreground)] transition-colors"
            title={order === "asc" ? "Ascending" : "Descending"}
          >
            {order === "asc" ? "↑ Asc" : "↓ Desc"}
          </button>
        </div>

        {failed && (
          <div className="rounded-lg border border-[var(--danger)]/30 bg-[var(--danger-bg)] text-[var(--danger)] text-sm px-4 py-3 mb-4">
            Couldn&apos;t reach the backend. Is it running?
          </div>
        )}

        {!failed && !games && <TableSkeleton />}

        {!failed && games && games.length === 0 && (
          <div className="text-sm text-[var(--muted)] py-8 text-center">
            No games match that search.
          </div>
        )}

        {!failed && games && games.length > 0 && (
          <>
            <div className="overflow-x-auto rounded-lg border border-[var(--border)]">
              <table className="text-sm border-collapse w-full">
                <thead>
                  <tr className="border-b border-[var(--border)]">
                    <th className="text-left py-2 px-3 text-[11px] uppercase tracking-wide font-medium text-[var(--muted)]">
                      Name
                    </th>
                    <th className="text-left py-2 px-3 text-[11px] uppercase tracking-wide font-medium text-[var(--muted)] hidden md:table-cell">
                      Genre
                    </th>
                    <th className="text-left py-2 px-3 text-[11px] uppercase tracking-wide font-medium text-[var(--muted)] hidden sm:table-cell">
                      Released
                    </th>
                    <th className="text-right py-2 px-3 text-[11px] uppercase tracking-wide font-medium text-[var(--muted)]">
                      Metacritic
                    </th>
                    <th className="text-left py-2 px-3 text-[11px] uppercase tracking-wide font-medium text-[var(--muted)] hidden lg:table-cell">
                      Platforms
                    </th>
                    <th className="text-right py-2 px-3 text-[11px] uppercase tracking-wide font-medium text-[var(--muted)]">
                      Price
                    </th>
                    <th className="text-right py-2 px-3 text-[11px] uppercase tracking-wide font-medium text-[var(--muted)] hidden sm:table-cell">
                      Score
                    </th>
                    <th className="text-right py-2 px-3 text-[11px] uppercase tracking-wide font-medium text-[var(--muted)] hidden md:table-cell">
                      Owners
                    </th>
                    <th className="text-right py-2 px-3 text-[11px] uppercase tracking-wide font-medium text-[var(--muted)]">
                      Peak players
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--border)] font-mono">
                  {games.map((g) => (
                    <tr key={g.name}>
                      <td className="py-2 px-3 truncate max-w-[220px] font-sans">{g.name}</td>
                      <td className="py-2 px-3 hidden md:table-cell text-[var(--muted)] truncate max-w-[160px]">
                        {g.genre ?? "—"}
                      </td>
                      <td className="py-2 px-3 hidden sm:table-cell text-[var(--muted)] whitespace-nowrap">
                        {formatDate(g.release_date)}
                      </td>
                      <td className="py-2 px-3 text-right tabular-nums">
                        {g.metacritic_score ?? "—"}
                      </td>
                      <td className="py-2 px-3 hidden lg:table-cell text-[var(--muted)]">
                        <PlatformBadges platforms={g.platforms} />
                      </td>
                      <td className="py-2 px-3 text-right tabular-nums">{formatPrice(g.price_usd)}</td>
                      <td className="py-2 px-3 hidden sm:table-cell text-right tabular-nums">
                        {g.review_score == null ? "—" : `${Math.round(g.review_score * 100)}%`}
                      </td>
                      <td className="py-2 px-3 hidden md:table-cell text-right tabular-nums text-[var(--muted)]">
                        {formatOwners(g.owners_low, g.owners_high)}
                      </td>
                      <td className="py-2 px-3 text-right tabular-nums">
                        {g.peak_ccu == null ? "—" : g.peak_ccu.toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="flex items-center justify-between mt-4 text-sm text-[var(--muted)]">
              <span>
                Page {page} of {totalPages}
              </span>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1}
                  className="panel rounded-md px-3 py-1.5 disabled:opacity-40 hover:text-[var(--foreground)] transition-colors"
                >
                  ← Prev
                </button>
                <button
                  type="button"
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages}
                  className="panel rounded-md px-3 py-1.5 disabled:opacity-40 hover:text-[var(--foreground)] transition-colors"
                >
                  Next →
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
