import { useState, useEffect, useCallback } from "react";
import type { PolymarketEvent, Platform } from "@/core/markets";
import { fetchEventBySlug } from "@/services/polymarket";
import { getBotMarketDetail } from "@/lib/messaging";
import { botMarketToEvent } from "@/services/markets";

interface UseMarketDetailReturn {
  event: PolymarketEvent | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

/**
 * Detect if a slug is a composite "platform/market_id" format.
 * Non-Polymarket slugs are formatted as "kalshi/abc123".
 */
function parseSlug(slug: string): { platform: Platform | null; marketId: string } {
  const knownPlatforms: Platform[] = ["kalshi", "opinion", "limitless", "myriad"];
  const firstSlash = slug.indexOf("/");
  if (firstSlash > 0) {
    const prefix = slug.substring(0, firstSlash) as Platform;
    if (knownPlatforms.includes(prefix)) {
      return { platform: prefix, marketId: slug.substring(firstSlash + 1) };
    }
  }
  return { platform: null, marketId: slug };
}

export function useMarketDetail(slug: string | null): UseMarketDetailReturn {
  const [event, setEvent] = useState<PolymarketEvent | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!slug) return;
    setLoading(true);
    setError(null);

    const { platform, marketId } = parseSlug(slug);

    try {
      if (platform) {
        // Non-Polymarket: fetch from Bot API
        const res = await getBotMarketDetail({ platform, marketId });
        if (!res.success || !res.data) {
          setError(res.error ?? "Market not found");
          return;
        }
        setEvent(botMarketToEvent(res.data));
      } else {
        // Polymarket: fetch from Gamma API
        const ev = await fetchEventBySlug(marketId);
        if (!ev) {
          setError("Market not found");
          return;
        }
        setEvent(ev);
      }
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
