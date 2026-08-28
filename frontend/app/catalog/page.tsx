import type { Metadata } from "next";
import CatalogClient from "./CatalogClient";

export const metadata: Metadata = {
  title: "Catalog | Ludo",
  description: "Browse the full 1,000-game catalog: search, filter by genre, and sort by score, price, or players.",
};

export default function CatalogPage() {
  return <CatalogClient />;
}
