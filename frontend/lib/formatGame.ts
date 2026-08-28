// Shared display formatting for a CatalogGame's fields -- extracted once
// a second real consumer (the film strip's cartridge detail card) needed
// the exact same formatting CatalogClient.tsx already had, rather than
// letting two components drift with their own copies of "how do we show
// a null price."

export function formatDate(iso: string | null): string {
  if (!iso) return "n/a";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "n/a";
  return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n % 1_000_000 === 0 ? 0 : 1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(n % 1_000 === 0 ? 0 : 1)}K`;
  return String(n);
}

export function formatOwners(low: number | null, high: number | null): string {
  if (low == null || high == null) return "n/a";
  return `${formatCount(low)} to ${formatCount(high)}`;
}

export function formatPrice(price: number | null): string {
  if (price == null) return "n/a";
  return price === 0 ? "Free" : `$${price.toFixed(2)}`;
}

export function formatPlatforms(platforms: string | null): string {
  if (!platforms) return "n/a";
  const labels: Record<string, string> = { windows: "Win", mac: "Mac", linux: "Linux" };
  return platforms
    .split(",")
    .map((p) => labels[p.trim()] ?? p.trim())
    .join(" · ");
}
