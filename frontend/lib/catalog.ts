// Backs app/catalog/page.tsx — the full-catalog browse page. Plain catalog
// lookups (GET /catalog, src/db/catalog.py), no LLM round trip, same as
// lib/genres.ts's fetchGamesByGenre.
import { API_BASE_URL } from "@/lib/api";

export interface CatalogGame {
  appid: number;
  name: string;
  developer: string | null;
  publisher: string | null;
  genre: string | null;
  release_date: string | null;
  metacritic_score: number | null;
  platforms: string | null;
  categories: string | null;
  price_usd: number | null;
  review_score: number | null;
  owners_low: number | null;
  owners_high: number | null;
  peak_ccu: number | null;
}

export type CatalogSort =
  | "peak_ccu"
  | "name"
  | "release_date"
  | "metacritic_score"
  | "price_usd"
  | "review_score"
  | "owners_high";

export interface CatalogQuery {
  q?: string;
  genre?: string;
  sort?: CatalogSort;
  order?: "asc" | "desc";
  page?: number;
  pageSize?: number;
}

export interface CatalogPage {
  games: CatalogGame[];
  total: number;
  page: number;
  page_size: number;
}

export async function fetchCatalog(
  query: CatalogQuery,
  signal?: AbortSignal
): Promise<CatalogPage> {
  const params = new URLSearchParams();
  if (query.q) params.set("q", query.q);
  if (query.genre) params.set("genre", query.genre);
  if (query.sort) params.set("sort", query.sort);
  if (query.order) params.set("order", query.order);
  if (query.page) params.set("page", String(query.page));
  if (query.pageSize) params.set("page_size", String(query.pageSize));

  const response = await fetch(`${API_BASE_URL}/catalog?${params.toString()}`, { signal });
  if (!response.ok) throw new Error(`catalog request failed (${response.status})`);
  return response.json();
}
