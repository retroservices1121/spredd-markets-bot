import { Skeleton } from "@/components/ui/skeleton";
import { PnlSummary } from "@/components/portfolio/PnlSummary";
import { PositionCard } from "@/components/portfolio/PositionCard";
import { usePositions, type PositionFilter } from "@/hooks/usePositions";
import { usePnlSummary } from "@/hooks/usePnlSummary";
import { RefreshCw, BarChart3 } from "lucide-react";
import { cn } from "@/lib/utils";

const FILTER_TABS: { id: PositionFilter; label: string }[] = [
  { id: "open", label: "Open" },
  { id: "closed", label: "Closed" },
  { id: "all", label: "All" },
];

export function PortfolioPage() {
  const { summary, loading: pnlLoading, refresh: refreshPnl } = usePnlSummary();
  const {
    positions,
    loading: posLoading,
    error,
    filter,
    setFilter,
    refresh: refreshPositions,
  } = usePositions();

  const loading = pnlLoading || posLoading;

  const refresh = () => {
    refreshPnl();
    refreshPositions();
  };

  return (
    <div className="p-4 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <BarChart3 className="w-4 h-4 text-spredd-orange" />
          <h2 className="text-sm font-bold text-foreground">Portfolio</h2>
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

      {/* PnL Summary */}
      {pnlLoading && !summary && (
        <Skeleton className="h-28 w-full rounded-xl" />
      )}
      {summary && <PnlSummary summary={summary} />}

      {/* Filter tabs */}
      <div className="flex gap-1.5">
        {FILTER_TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setFilter(tab.id)}
            className={cn(
              "px-3 py-1.5 text-xs rounded-lg border transition-colors",
              filter === tab.id
                ? "border-spredd-orange text-spredd-orange bg-spredd-orange/10"
                : "border-border text-muted-foreground hover:text-foreground hover:border-foreground/30"
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Error state */}
      {error && (
        <div className="text-sm text-spredd-red text-center py-4">{error}</div>
      )}

      {/* Loading skeletons */}
      {posLoading && positions.length === 0 && (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-24 w-full rounded-xl" />
          ))}
        </div>
      )}

      {/* Position list */}
      {positions.length > 0 && (
        <div className="space-y-2">
          {positions.map((pos) => (
            <PositionCard key={pos.id} position={pos} />
          ))}
        </div>
      )}

      {/* Empty state */}
      {!posLoading && positions.length === 0 && !error && (
        <div className="text-center py-8">
          <BarChart3 className="w-8 h-8 text-muted-foreground mx-auto mb-2" />
          <p className="text-sm text-muted-foreground">
            {filter === "open"
              ? "No open positions"
              : filter === "closed"
              ? "No closed positions"
              : "No positions yet"}
          </p>
          <p className="text-xs text-muted-foreground mt-1">
            Start trading to build your portfolio
          </p>
        </div>
      )}
    </div>
  );
}
