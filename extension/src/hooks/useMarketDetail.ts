import { useState, useEffect, useCallback } from "react";
import type { PolymarketEvent, Orderbook } from "@/core/markets";
import { fetchEventBySlug, getOrderBook } from "@/services/polymarket";

interface UseMarketDetailReturn {
  event: PolymarketEvent | null;
  orderbooks: Record<string, Orderbook>;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

export function useMarketDetail(slug: string | null): UseMarketDetailReturn {
  const [event, setEvent] = useState<PolymarketEvent | null>(null);
  const [orderbooks, setOrderbooks] = useState<Record<string, Orderbook>>({});
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

      // Fetch orderbooks for all market outcomes in parallel
      const books: Record<string, Orderbook> = {};
      const tokenIds = ev.markets.flatMap((m) =>
        m.outcomes.filter((o) => o.tokenId).map((o) => o.tokenId)
      );

      const results = await Promise.allSettled(
        tokenIds.map(async (tid) => {
          const ob = await getOrderBook(tid);
          return { tid, ob };
        })
      );

      for (const r of results) {
        if (r.status === "fulfilled") {
          books[r.value.tid] = r.value.ob;
        }
      }

      setOrderbooks(books);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load market");
    } finally {
      setLoading(false);
    }
  }, [slug]);

  useEffect(() => {
    load();
  }, [load]);

  return { event, orderbooks, loading, error, refresh: load };
}
