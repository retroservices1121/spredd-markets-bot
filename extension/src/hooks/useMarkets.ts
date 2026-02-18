import { useState, useEffect, useCallback, useRef } from "react";
import type { PolymarketEvent } from "@/core/markets";
import { fetchEvents, searchEvents } from "@/services/polymarket";
import { getBotMarkets, searchBotMarkets } from "@/lib/messaging";
import { botMarketsToEvents } from "@/services/markets";
import type { PlatformFilter } from "@/components/markets/PlatformTabs";

interface UseMarketsReturn {
  events: PolymarketEvent[];
  loading: boolean;
  error: string | null;
  searchQuery: string;
  setSearchQuery: (q: string) => void;
  loadMore: () => void;
  hasMore: boolean;
  refresh: () => void;
}

const PAGE_SIZE = 20;

export function useMarkets(platform: PlatformFilter = "all"): UseMarketsReturn {
  const [events, setEvents] = useState<PolymarketEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);

  // Debounce timer ref
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  const isPolymarket = platform === "polymarket";
  const useGammaApi = isPolymarket;

  // Load initial/trending markets
  const loadInitial = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (useGammaApi) {
        // Polymarket: use Gamma API (public, fast)
        const data = await fetchEvents(PAGE_SIZE, 0);
        setEvents(data);
        setOffset(PAGE_SIZE);
        setHasMore(data.length === PAGE_SIZE);
      } else {
        // Other platforms or "all": use Bot API
        const res = await getBotMarkets({
          platform: platform === "all" ? undefined : platform,
          limit: PAGE_SIZE,
          active: true,
        });
        if (res.success && res.data) {
          const data = Array.isArray(res.data) ? res.data : [];
          setEvents(botMarketsToEvents(data));
          setHasMore(data.length === PAGE_SIZE);
        } else {
          setError(res.error ?? "Failed to load markets");
          setEvents([]);
          setHasMore(false);
        }
        setOffset(PAGE_SIZE);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load markets");
    } finally {
      setLoading(false);
    }
  }, [platform, useGammaApi]);

  // Search markets with debounce
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);

    if (!searchQuery.trim()) {
      loadInitial();
      return;
    }

    debounceRef.current = setTimeout(async () => {
      setLoading(true);
      setError(null);
      try {
        if (useGammaApi) {
          const data = await searchEvents(searchQuery.trim());
          setEvents(data);
        } else {
          const res = await searchBotMarkets({
            query: searchQuery.trim(),
            platform: platform === "all" ? undefined : platform,
          });
          if (res.success && res.data) {
            const data = Array.isArray(res.data) ? res.data : [];
            setEvents(botMarketsToEvents(data));
          } else {
            setError(res.error ?? "Search failed");
            setEvents([]);
          }
        }
        setHasMore(false); // search results are not paginated
      } catch (e) {
        setError(e instanceof Error ? e.message : "Search failed");
      } finally {
        setLoading(false);
      }
    }, 300);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [searchQuery, loadInitial, useGammaApi, platform]);

  // Load more (pagination for trending view only)
  const loadMore = useCallback(async () => {
    if (searchQuery.trim() || loading || !hasMore) return;
    setLoading(true);
    try {
      if (useGammaApi) {
        const data = await fetchEvents(PAGE_SIZE, offset);
        setEvents((prev) => [...prev, ...data]);
        setOffset((prev) => prev + PAGE_SIZE);
        setHasMore(data.length === PAGE_SIZE);
      }
      // Bot API pagination could be added later
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load more");
    } finally {
      setLoading(false);
    }
  }, [searchQuery, loading, hasMore, offset, useGammaApi]);

  const refresh = useCallback(() => {
    setSearchQuery("");
    setOffset(0);
    loadInitial();
  }, [loadInitial]);

  return {
    events,
    loading,
    error,
    searchQuery,
    setSearchQuery,
    loadMore,
    hasMore,
    refresh,
  };
}
