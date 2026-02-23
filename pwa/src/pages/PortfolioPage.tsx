import { Loader2, RefreshCw, TrendingUp, TrendingDown } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { usePositions, type PositionFilter } from "@/hooks/usePositions";
import { formatUSD, formatPercent, platformLabel } from "@/lib/utils";
import { cn } from "@/lib/utils";

const FILTERS: { value: PositionFilter; label: string }[] = [
  { value: "open", label: "Open" },
  { value: "closed", label: "Closed" },
  { value: "all", label: "All" },
];

export function PortfolioPage() {
  const { positions, loading, error, filter, setFilter, refresh } =
    usePositions();

  const totalPnl = positions.reduce((sum, p) => sum + p.pnl, 0);
  const totalValue = positions.reduce(
    (sum, p) => sum + p.token_amount * p.current_price,
    0
  );

  return (
    <div className="min-h-[100dvh] bg-spredd-black pb-20 pt-14">
      {/* Header */}
      <div className="px-5 py-4">
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-2xl font-bold text-white">Portfolio</h1>
          <button
            onClick={refresh}
            className="text-white/40 hover:text-white transition-colors"
          >
            <RefreshCw size={18} />
          </button>
        </div>

        {/* Summary cards */}
        <div className="grid grid-cols-2 gap-3 mb-5">
          <Card className="bg-spredd-dark border-white/5">
            <CardContent className="p-3">
              <p className="text-xs text-white/50 mb-1">Total Value</p>
              <p className="text-lg font-bold text-white">
                {formatUSD(totalValue)}
              </p>
            </CardContent>
          </Card>
          <Card className="bg-spredd-dark border-white/5">
            <CardContent className="p-3">
              <p className="text-xs text-white/50 mb-1">Total PnL</p>
              <p
                className={cn(
                  "text-lg font-bold",
                  totalPnl >= 0 ? "text-spredd-green" : "text-spredd-red"
                )}
              >
                {totalPnl >= 0 ? "+" : ""}
                {formatUSD(totalPnl)}
              </p>
            </CardContent>
          </Card>
        </div>

        {/* Filter tabs */}
        <div className="flex gap-2 mb-4">
          {FILTERS.map(({ value, label }) => (
            <button
              key={value}
              onClick={() => setFilter(value)}
              className={cn(
                "px-4 py-1.5 rounded-full text-sm font-medium transition-all",
                filter === value
                  ? "bg-spredd-orange text-white"
                  : "bg-spredd-surface text-white/50"
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Positions list */}
      <div className="px-5 space-y-3">
        {loading && positions.length === 0 && (
          <>
            {[1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-24 w-full rounded-xl" />
            ))}
          </>
        )}

        {error && (
          <p className="text-center text-white/40 py-8">{error}</p>
        )}

        {!loading && positions.length === 0 && (
          <div className="text-center py-12">
            <p className="text-white/40 mb-2">No positions yet</p>
            <p className="text-white/25 text-sm">
              Start trading from the feed to see your positions here
            </p>
          </div>
        )}

        {positions.map((pos) => {
          const pnlPercent =
            pos.entry_price > 0
              ? ((pos.current_price - pos.entry_price) / pos.entry_price) * 100
              : 0;
          const isProfit = pos.pnl >= 0;

          return (
            <Card
              key={pos.id}
              className="bg-spredd-dark border-white/5 overflow-hidden"
            >
              <CardContent className="p-4">
                <div className="flex items-start justify-between mb-2">
                  <div className="flex-1 pr-3">
                    <p className="text-sm font-medium text-white leading-tight">
                      {pos.market_title}
                    </p>
                    <div className="flex items-center gap-2 mt-1">
                      <Badge variant="platform" className="text-[10px]">
                        {platformLabel(pos.platform)}
                      </Badge>
                      <span
                        className={cn(
                          "text-xs font-bold px-2 py-0.5 rounded-full",
                          pos.outcome.toLowerCase() === "yes"
                            ? "bg-spredd-green/20 text-spredd-green"
                            : "bg-spredd-red/20 text-spredd-red"
                        )}
                      >
                        {pos.outcome}
                      </span>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="flex items-center gap-1">
                      {isProfit ? (
                        <TrendingUp size={14} className="text-spredd-green" />
                      ) : (
                        <TrendingDown size={14} className="text-spredd-red" />
                      )}
                      <span
                        className={cn(
                          "text-sm font-bold",
                          isProfit ? "text-spredd-green" : "text-spredd-red"
                        )}
                      >
                        {isProfit ? "+" : ""}
                        {formatUSD(pos.pnl)}
                      </span>
                    </div>
                    <p className="text-xs text-white/40 mt-0.5">
                      {pnlPercent >= 0 ? "+" : ""}
                      {pnlPercent.toFixed(1)}%
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-4 text-xs text-white/40">
                  <span>
                    {pos.token_amount.toFixed(2)} shares @ {formatPercent(pos.entry_price)}
                  </span>
                  <span>Now {formatPercent(pos.current_price)}</span>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
