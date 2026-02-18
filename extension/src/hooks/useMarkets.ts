import { useState, useEffect, useCallback, useRef } from "react";
import type { PolymarketEvent } from "@/core/markets";
import { fetchEvents, searchEvents } from "@/services/polymarket";

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

export function useMarkets(): UseMarketsReturn {
  const [events, setEvents] = useState<PolymarketEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);

  // Debounce timer ref
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  // Load initial/trending markets
  const loadInitial = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchEvents(PAGE_SIZE, 0);
      setEvents(data);
      setOffset(PAGE_SIZE);
      setHasMore(data.length === PAGE_SIZE);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load markets");
    } finally {
      setLoading(false);
    }
  }, []);

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
        const data = await searchEvents(searchQuery.trim());
        setEvents(data);
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
  }, [searchQuery, loadInitial]);

  // Load more (pagination for trending view only)
  const loadMore = useCallback(async () => {
    if (searchQuery.trim() || loading || !hasMore) return;
    setLoading(true);
    try {
      const data = await fetchEvents(PAGE_SIZE, offset);
      setEvents((prev) => [...prev, ...data]);
      setOffset((prev) => prev + PAGE_SIZE);
      setHasMore(data.length === PAGE_SIZE);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load more");
    } finally {
      setLoading(false);
    }
  }, [searchQuery, loading, hasMore, offset]);

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
