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

// Per-platform cache so switching tabs is instant
const cache = new Map<string, { events: PolymarketEvent[]; ts: number }>();
const CACHE_TTL = 60_000; // 1 minute

function getCached(key: string): PolymarketEvent[] | null {
  const entry = cache.get(key);
  if (entry && Date.now() - entry.ts < CACHE_TTL) return entry.events;
  return null;
}

function setCache(key: string, events: PolymarketEvent[]) {
  cache.set(key, { events, ts: Date.now() });
}

export function useMarkets(platform: PlatformFilter = "all"): UseMarketsReturn {
  const [events, setEvents] = useState<PolymarketEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);

  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  // "all" and "polymarket" use the fast Gamma API; others use Bot API
  const useGammaApi = platform === "polymarket" || platform === "all";

  // Load initial/trending markets
  const loadInitial = useCallback(async () => {
    // Check cache first for instant tab switching
    const cached = getCached(platform);
    if (cached) {
      setEvents(cached);
      setLoading(false);
      setError(null);
      setHasMore(platform === "polymarket" || platform === "all");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      if (useGammaApi) {
        const data = await fetchEvents(PAGE_SIZE, 0);
        setEvents(data);
        setOffset(PAGE_SIZE);
        setHasMore(data.length === PAGE_SIZE);
        setCache(platform, data);
      } else {
        const res = await getBotMarkets({
          platform,
          limit: PAGE_SIZE,
          active: true,
        });
        if (res.success && res.data) {
          const data = Array.isArray(res.data) ? res.data : [];
          const converted = botMarketsToEvents(data);
          setEvents(converted);
          setHasMore(data.length === PAGE_SIZE);
          setCache(platform, converted);
        } else {
          const msg = res.error ?? "Failed to load markets";
          // Friendlier message for server errors
          setError(
            msg.includes("502") || msg.includes("503")
              ? "Platform temporarily unavailable. Try again later."
              : msg
          );
          setEvents([]);
          setHasMore(false);
        }
        setOffset(PAGE_SIZE);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Failed to load markets";
      setError(
        msg.includes("502") || msg.includes("503")
          ? "Platform temporarily unavailable. Try again later."
          : msg
      );
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
            platform,
          });
          if (res.success && res.data) {
            const data = Array.isArray(res.data) ? res.data : [];
            setEvents(botMarketsToEvents(data));
          } else {
            const msg = res.error ?? "Search failed";
            setError(
              msg.includes("502") || msg.includes("503")
                ? "Platform temporarily unavailable. Try again later."
                : msg
            );
            setEvents([]);
          }
        }
        setHasMore(false);
      } catch (e) {
        const msg = e instanceof Error ? e.message : "Search failed";
        setError(
          msg.includes("502") || msg.includes("503")
            ? "Platform temporarily unavailable. Try again later."
            : msg
        );
      } finally {
        setLoading(false);
      }
    }, 300);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [searchQuery, loadInitial, useGammaApi, platform]);

  // Load more (pagination for Gamma API only)
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
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load more");
    } finally {
      setLoading(false);
    }
  }, [searchQuery, loading, hasMore, offset, useGammaApi]);

  const refresh = useCallback(() => {
    // Clear cache for this platform on manual refresh
    cache.delete(platform);
    setSearchQuery("");
    setOffset(0);
    loadInitial();
  }, [loadInitial, platform]);

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
