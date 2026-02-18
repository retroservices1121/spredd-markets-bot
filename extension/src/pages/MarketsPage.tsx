import { useState, useEffect, useMemo } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { MarketSearch } from "@/components/markets/MarketSearch";
import { MarketCard } from "@/components/markets/MarketCard";
import { PlatformTabs, type PlatformFilter } from "@/components/markets/PlatformTabs";
import { CategoryTabs } from "@/components/markets/CategoryTabs";
import { useMarkets } from "@/hooks/useMarkets";
import { RefreshCw, TrendingUp } from "lucide-react";

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

  // Extract unique categories from events
  const categories = useMemo(
    () => [...new Set(events.map((e) => e.category).filter(Boolean))],
    [events]
  );

  // Filter events by selected category
  const filteredEvents = useMemo(
    () => category === "all" ? events : events.filter((e) => e.category === category),
    [events, category]
  );

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
