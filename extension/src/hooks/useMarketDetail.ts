import { useState, useEffect, useCallback } from "react";
import type { PolymarketEvent } from "@/core/markets";
import { fetchEventBySlug } from "@/services/polymarket";

interface UseMarketDetailReturn {
  event: PolymarketEvent | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

export function useMarketDetail(slug: string | null): UseMarketDetailReturn {
  const [event, setEvent] = useState<PolymarketEvent | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!slug) return;
    setLoading(true);
    setError(null);

    try {
      const ev = await fetchEventBySlug(slug);
      if (!ev) {
        setError("Market not found");
        return;
      }
      setEvent(ev);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load market");
    } finally {
      setLoading(false);
    }
  }, [slug]);

  useEffect(() => {
    load();
  }, [load]);

  return { event, loading, error, refresh: load };
}
