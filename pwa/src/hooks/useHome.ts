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

const MOCK_MARKETS: FeedMarket[] = [
  {
    id: "will-bitcoin-hit-100k-2025",
    platform: "polymarket",
    title: "Will Bitcoin hit $100K in 2025?",
    image: "https://images.unsplash.com/photo-1518546305927-5a555bb7020d?w=800&h=600&fit=crop",
    yes_price: 0.72,
    no_price: 0.28,
    volume: 4520000,
    category: "Crypto",
    end_date: "2025-12-31T23:59:59Z",
  },
  {
    id: "trump-wins-2028",
    platform: "polymarket",
    title: "Will Trump win the 2028 Presidential Election?",
    image: "https://images.unsplash.com/photo-1540910419892-4a36d2c3266c?w=800&h=600&fit=crop",
    yes_price: 0.35,
    no_price: 0.65,
    volume: 12300000,
    category: "Politics",
    end_date: "2028-11-03T23:59:59Z",
  },
  {
    id: "fed-rate-cut-march",
    platform: "kalshi",
    title: "Will the Fed cut rates in March 2026?",
    image: "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?w=800&h=600&fit=crop",
    yes_price: 0.58,
    no_price: 0.42,
    volume: 890000,
    category: "Economics",
    end_date: "2026-03-19T18:00:00Z",
  },
  {
    id: "ai-passes-bar-exam",
    platform: "polymarket",
    title: "Will an AI system score 90%+ on the Bar Exam by 2026?",
    image: "https://images.unsplash.com/photo-1677442136019-21780ecad995?w=800&h=600&fit=crop",
    yes_price: 0.84,
    no_price: 0.16,
    volume: 1560000,
    category: "AI",
    end_date: "2026-12-31T23:59:59Z",
  },
  {
    id: "spacex-starship-orbit",
    platform: "kalshi",
    title: "Will SpaceX Starship reach orbit successfully?",
    image: "https://images.unsplash.com/photo-1516849841032-87cbac4d88f7?w=800&h=600&fit=crop",
    yes_price: 0.91,
    no_price: 0.09,
    volume: 2100000,
    category: "Science",
    end_date: "2026-06-30T23:59:59Z",
  },
  {
    id: "us-recession-2026",
    platform: "kalshi",
    title: "Will the US enter a recession in 2026?",
    image: "https://images.unsplash.com/photo-1590283603385-17ffb3a7f29f?w=800&h=600&fit=crop",
    yes_price: 0.31,
    no_price: 0.69,
    volume: 5400000,
    category: "Economics",
    end_date: "2026-12-31T23:59:59Z",
  },
  {
    id: "eth-flips-btc",
    platform: "limitless",
    title: "Will Ethereum flip Bitcoin by market cap?",
    image: "https://images.unsplash.com/photo-1622630998477-20aa696ecb05?w=800&h=600&fit=crop",
    yes_price: 0.08,
    no_price: 0.92,
    volume: 340000,
    category: "Crypto",
    end_date: "2026-12-31T23:59:59Z",
  },
  {
    id: "tiktok-ban-us",
    platform: "polymarket",
    title: "Will TikTok be banned in the US by end of 2026?",
    image: "https://images.unsplash.com/photo-1611162616475-46b635cb6868?w=800&h=600&fit=crop",
    yes_price: 0.22,
    no_price: 0.78,
    volume: 3200000,
    category: "Politics",
    end_date: "2026-12-31T23:59:59Z",
  },
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

  const useMockData = useCallback(() => {
    setFeatured(MOCK_MARKETS.slice(0, 4));
    setLive(MOCK_MARKETS.filter((m) => m.end_date && new Date(m.end_date) > new Date()).slice(0, 5));
    setMarkets(MOCK_MARKETS);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const [trendingRes, feedRes, catRes] = await Promise.allSettled([
        getTrending(5),
        getFeed(undefined, 12),
        getCategories(),
      ]);

      let hasData = false;

      if (trendingRes.status === "fulfilled" && trendingRes.value.markets.length > 0) {
        setFeatured(trendingRes.value.markets.slice(0, 5));
        hasData = true;
      }

      if (feedRes.status === "fulfilled" && feedRes.value.markets.length > 0) {
        const all = feedRes.value.markets;
        setLive(all.filter((m) => m.end_date && new Date(m.end_date) > new Date()).slice(0, 5));
        setMarkets(all);
        hasData = true;
      }

      if (catRes.status === "fulfilled" && catRes.value.categories.length > 0) {
        setCategories([{ id: "all", name: "All" }, ...catRes.value.categories]);
      }

      // Fall back to mock data if API returned nothing useful
      if (!hasData) {
        useMockData();
      }
    } catch {
      useMockData();
    } finally {
      setLoading(false);
    }
  }, [useMockData]);

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
