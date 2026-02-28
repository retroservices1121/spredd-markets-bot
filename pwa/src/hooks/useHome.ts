import { useState, useEffect, useCallback } from "react";
import {
  getFeed,
  getTrending,
  getCategories,
  type FeedMarket,
  type Category,
} from "@/api/client";

const DEFAULT_CATEGORIES: Category[] = [
  { id: "all", name: "All" },
  { id: "crypto", name: "Crypto" },
  { id: "politics", name: "Politics" },
  { id: "sports", name: "Sports" },
  { id: "ai", name: "AI" },
  { id: "economics", name: "Economics" },
  { id: "science", name: "Science" },
];

interface UseHomeReturn {
  categories: Category[];
  selectedCategory: string;
  setSelectedCategory: (id: string) => void;
  featured: FeedMarket[];
  live: FeedMarket[];
  markets: FeedMarket[];
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

export function useHome(): UseHomeReturn {
  const [categories, setCategories] = useState<Category[]>(DEFAULT_CATEGORIES);
  const [selectedCategory, setSelectedCategory] = useState("all");
  const [featured, setFeatured] = useState<FeedMarket[]>([]);
  const [live, setLive] = useState<FeedMarket[]>([]);
  const [markets, setMarkets] = useState<FeedMarket[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const [trendingRes, feedRes, catRes] = await Promise.allSettled([
        getTrending(5),
        getFeed(undefined, 12),
        getCategories(),
      ]);

      if (trendingRes.status === "fulfilled") {
        setFeatured(trendingRes.value.markets.slice(0, 5));
      }

      if (feedRes.status === "fulfilled") {
        const all = feedRes.value.markets;
        setLive(all.filter((m) => m.end_date && new Date(m.end_date) > new Date()).slice(0, 5));
        setMarkets(all);
      }

      if (catRes.status === "fulfilled" && catRes.value.categories.length > 0) {
        setCategories([{ id: "all", name: "All" }, ...catRes.value.categories]);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return {
    categories,
    selectedCategory,
    setSelectedCategory,
    featured,
    live,
    markets,
    loading,
    error,
    refresh: load,
  };
}
