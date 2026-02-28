import { useState, useCallback, useRef, useEffect } from "react";
import { getFeed, type FeedMarket } from "@/api/client";

// TODO: Remove mock data when backend is running
const MOCK_MARKETS: FeedMarket[] = [
  {
    id: "will-bitcoin-hit-100k-2025",
    platform: "polymarket",
    title: "Will Bitcoin hit $100K in 2025?",
    image: "https://images.unsplash.com/photo-1518546305927-5a555bb7020d?w=800&h=1200&fit=crop",
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
    image: "https://images.unsplash.com/photo-1540910419892-4a36d2c3266c?w=800&h=1200&fit=crop",
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
    image: "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?w=800&h=1200&fit=crop",
    yes_price: 0.58,
    no_price: 0.42,
    volume: 890000,
    category: "Economics",
    end_date: "2026-03-19T18:00:00Z",
  },
  {
    id: "eth-flips-btc",
    platform: "limitless",
    title: "Will Ethereum flip Bitcoin by market cap?",
    image: "https://images.unsplash.com/photo-1622630998477-20aa696ecb05?w=800&h=1200&fit=crop",
    yes_price: 0.08,
    no_price: 0.92,
    volume: 340000,
    category: "Crypto",
    end_date: "2026-12-31T23:59:59Z",
  },
  {
    id: "ai-passes-bar-exam",
    platform: "polymarket",
    title: "Will an AI system score 90%+ on the Bar Exam by 2026?",
    image: "https://images.unsplash.com/photo-1677442136019-21780ecad995?w=800&h=1200&fit=crop",
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
    image: "https://images.unsplash.com/photo-1516849841032-87cbac4d88f7?w=800&h=1200&fit=crop",
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
    image: "https://images.unsplash.com/photo-1590283603385-17ffb3a7f29f?w=800&h=1200&fit=crop",
    yes_price: 0.31,
    no_price: 0.69,
    volume: 5400000,
    category: "Economics",
    end_date: "2026-12-31T23:59:59Z",
  },
  {
    id: "tiktok-ban-us",
    platform: "polymarket",
    title: "Will TikTok be banned in the US by end of 2026?",
    image: "https://images.unsplash.com/photo-1611162616475-46b635cb6868?w=800&h=1200&fit=crop",
    yes_price: 0.22,
    no_price: 0.78,
    volume: 3200000,
    category: "Politics",
    end_date: "2026-12-31T23:59:59Z",
  },
];

interface UseFeedReturn {
  markets: FeedMarket[];
  loading: boolean;
  error: string | null;
  hasMore: boolean;
  loadMore: () => void;
  refresh: () => void;
}

export function useFeed(): UseFeedReturn {
  const [markets, setMarkets] = useState<FeedMarket[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(true);
  const cursorRef = useRef<number | null>(null);
  const loadingRef = useRef(false);

  const load = useCallback(async (reset = false) => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    if (reset) setLoading(true);
    setError(null);

    try {
      const cursor = reset ? undefined : cursorRef.current ?? undefined;
      const res = await getFeed(cursor);
      const raw = res.markets || [];

      // Normalize API response: volume can be string, prices can be missing
      const newMarkets: FeedMarket[] = raw.map((m: any) => ({
        id: String(m.id || ""),
        platform: String(m.platform || ""),
        title: String(m.title || m.question || ""),
        image: m.image ? String(m.image) : undefined,
        yes_price: Number(m.yes_price ?? 0.5),
        no_price: Number(m.no_price ?? 0.5),
        volume: Number(m.volume ?? 0) || 0,
        category: m.category ? String(m.category) : undefined,
        end_date: m.end_date ? String(m.end_date) : m.endDate ? String(m.endDate) : undefined,
      }));

      // If API returned markets, use them; mix in mocks if too few have images
      const withImages = newMarkets.filter((m) => m.image);
      const finalMarkets = withImages.length >= 3 ? newMarkets : [...newMarkets, ...MOCK_MARKETS];

      setMarkets((prev) => (reset ? finalMarkets : [...prev, ...finalMarkets]));
      cursorRef.current = res.next_cursor;
      setHasMore(res.next_cursor != null && raw.length > 0);
    } catch {
      // Backend not available — fall back to mock data
      if (reset || markets.length === 0) {
        setMarkets(MOCK_MARKETS);
        setHasMore(false);
      }
    } finally {
      setLoading(false);
      loadingRef.current = false;
    }
  }, []);

  useEffect(() => {
    load(true);
  }, [load]);

  const loadMore = useCallback(() => {
    if (hasMore && !loadingRef.current) load(false);
  }, [hasMore, load]);

  const refresh = useCallback(() => {
    cursorRef.current = null;
    load(true);
  }, [load]);

  return { markets, loading, error, hasMore, loadMore, refresh };
}
