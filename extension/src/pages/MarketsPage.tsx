import { Skeleton } from "@/components/ui/skeleton";
import { MarketSearch } from "@/components/markets/MarketSearch";
import { MarketCard } from "@/components/markets/MarketCard";
import { useMarkets } from "@/hooks/useMarkets";
import { RefreshCw, TrendingUp } from "lucide-react";

interface MarketsPageProps {
  onSelectEvent: (slug: string) => void;
}

export function MarketsPage({ onSelectEvent }: MarketsPageProps) {
  const {
    events,
    loading,
    error,
    searchQuery,
    setSearchQuery,
    refresh,
  } = useMarkets();

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

      {/* Search */}
      <MarketSearch value={searchQuery} onChange={setSearchQuery} />

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
      {events.length > 0 && (
        <div className="space-y-2">
          {events.map((event) => (
            <MarketCard
              key={event.id}
              event={event}
              onClick={() => onSelectEvent(event.slug)}
            />
          ))}
        </div>
      )}

      {/* Empty state */}
      {!loading && events.length === 0 && !error && (
        <p className="text-sm text-muted-foreground text-center py-8">
          {searchQuery ? "No markets found" : "No active markets"}
        </p>
      )}
    </div>
  );
}
