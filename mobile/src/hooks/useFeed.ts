import { useState, useCallback, useRef, useEffect } from "react";
import { getFeed, type FeedMarket } from "@/api/client";

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

      const newMarkets: FeedMarket[] = raw.map((m: any) => ({
        id: String(m.id || ""),
        platform: String(m.platform || ""),
        title: String(m.title || m.question || ""),
        image: m.image ? String(m.image) : undefined,
        yes_price: Number(m.yes_price ?? 0.5),
        no_price: Number(m.no_price ?? 0.5),
        volume: Number(m.volume ?? 0) || 0,
        category: m.category ? String(m.category) : undefined,
        end_date: m.end_date
          ? String(m.end_date)
          : m.endDate
            ? String(m.endDate)
            : undefined,
      }));

      setMarkets((prev) => (reset ? newMarkets : [...prev, ...newMarkets]));
      cursorRef.current = res.next_cursor;
      setHasMore(res.next_cursor != null && raw.length > 0);
    } catch {
      setError("Unable to load markets. Please try again.");
      if (reset) {
        setMarkets([]);
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
