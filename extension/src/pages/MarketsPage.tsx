import { useState, useEffect, useMemo } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { MarketSearch } from "@/components/markets/MarketSearch";
import { MarketCard } from "@/components/markets/MarketCard";
import { PlatformTabs, type PlatformFilter } from "@/components/markets/PlatformTabs";
import { CategoryTabs } from "@/components/markets/CategoryTabs";
import { useMarkets } from "@/hooks/useMarkets";
import { RefreshCw, TrendingUp } from "lucide-react";

/** Rapid-market detection: ticker pattern, title keywords, or ends within 2 hours */
const RAPID_TITLE_RE =
  /\b(5[\s-]?min|15[\s-]?min|30[\s-]?min|1[\s-]?hour|2[\s-]?hour|hourly|minute|quick|rapid|flash)\b/i;
const TWO_HOURS_MS = 2 * 60 * 60 * 1000;

/**
 * Kalshi rapid-market ticker prefixes:
 *   15-minute: KXBTC15M, KXETH15M, KXSOL15M, KXXRP15M, KXDOGE15M
 *   Hourly:    KXBTCD, KXETHD, KXSOLD, KXXRPD, KXDOGED
 *   5-minute:  KXBTC5M, KXETH5M, KXSOL5M, etc.
 */
const RAPID_TICKER_RE =
  /^kalshi\/(KX\w+(?:5M|15M|30M)|KXBTCD|KXETHD|KXSOLD|KXXRPD|KXDOGED)/i;

function isRapidMarket(event: { endDate: string; title: string; slug: string }, now: number): boolean {
  if (RAPID_TICKER_RE.test(event.slug)) return true;
  if (RAPID_TITLE_RE.test(event.title)) return true;
  if (event.endDate) {
    const end = new Date(event.endDate).getTime();
    if (end > now && end - now <= TWO_HOURS_MS) return true;
  }
  return false;
}

interface MarketsPageProps {
  onSelectEvent: (slug: string) => void;
}

export function MarketsPage({ onSelectEvent }: MarketsPageProps) {
  const [platform, setPlatform] = useState<PlatformFilter>("polymarket");
  const [category, setCategory] = useState<string>("all");

  const {
    events,
    loading,
    error,
    searchQuery,
    setSearchQuery,
    refresh,
  } = useMarkets(platform);

  // Reset category when platform changes
  useEffect(() => {
    setCategory("all");
  }, [platform]);

  // Extract unique categories from events, with synthetic ones first
  const categories = useMemo(() => {
    const apiCats = [...new Set(events.map((e) => e.category).filter(Boolean))];
    const synthetic: string[] = [];
    // Always show Trending and Rapid — these are the hottest tabs
    if (events.length >= 5) synthetic.push("Trending");
    synthetic.push("Rapid");
    return [...synthetic, ...apiCats];
  }, [events]);

  // Filter events by selected category
  const filteredEvents = useMemo(() => {
    if (category === "all") return events;
    if (category === "Trending") {
      return [...events].sort((a, b) => b.volume - a.volume).slice(0, 10);
    }
    if (category === "Rapid") {
      const now = Date.now();
      return events
        .filter((e) => isRapidMarket(e, now))
        .sort((a, b) => {
          // Sort by soonest ending first
          const aEnd = a.endDate ? new Date(a.endDate).getTime() : Infinity;
          const bEnd = b.endDate ? new Date(b.endDate).getTime() : Infinity;
          return aEnd - bEnd;
        });
    }
    return events.filter((e) => e.category === category);
  }, [events, category]);

  return (
    <div className="p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <TrendingUp className="w-4 h-4 text-spredd-orange" />
          <h2 className="text-sm font-bold text-foreground">Markets</h2>
        </div>
        <button
          onClick={refresh}
          disabled={loading}
          className="p-2 rounded-lg hover:bg-secondary transition-colors disabled:opacity-50"
        >
          <RefreshCw
            className={`w-4 h-4 text-muted-foreground ${loading ? "animate-spin" : ""}`}
          />
        </button>
      </div>

      {/* Platform tabs */}
      <PlatformTabs selected={platform} onChange={setPlatform} />

      {/* Search */}
      <MarketSearch value={searchQuery} onChange={setSearchQuery} />

      {/* Category tabs */}
      {categories.length > 1 && (
        <CategoryTabs categories={categories} selected={category} onChange={setCategory} />
      )}

      {/* Error state */}
      {error && (
        <div className="text-sm text-spredd-red text-center py-4">
          {error}
        </div>
      )}

      {/* Loading skeletons */}
      {loading && events.length === 0 && (
        <div className="space-y-3">
          {[1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} className="h-24 w-full rounded-xl" />
          ))}
        </div>
      )}

      {/* Market list */}
      {filteredEvents.length > 0 && (
        <div className="space-y-2">
          {filteredEvents.map((event) => (
            <MarketCard
              key={event.id}
              event={event}
              onClick={() => onSelectEvent(event.slug)}
              showPlatform={platform === "all"}
            />
          ))}
        </div>
      )}

      {/* Empty state */}
      {!loading && filteredEvents.length === 0 && !error && (
        <p className="text-sm text-muted-foreground text-center py-8">
          {searchQuery ? "No markets found" : "No active markets"}
        </p>
      )}
    </div>
  );
}
