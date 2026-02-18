import { TrendingUp, TrendingDown } from "lucide-react";
import { formatUSD } from "@/lib/utils";
import { cn } from "@/lib/utils";
import type { PnlSummaryData } from "@/core/markets";

interface PnlSummaryProps {
  summary: PnlSummaryData;
}

export function PnlSummary({ summary }: PnlSummaryProps) {
  const isPositive = summary.total_pnl >= 0;

  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-xl border p-4",
        isPositive
          ? "bg-gradient-to-br from-spredd-green/20 via-spredd-green/10 to-transparent border-spredd-green/20"
          : "bg-gradient-to-br from-spredd-red/20 via-spredd-red/10 to-transparent border-spredd-red/20"
      )}
    >
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs text-muted-foreground mb-1">Total P&L</p>
          <div className="flex items-center gap-2">
            <p
              className={cn(
                "text-2xl font-bold",
                isPositive ? "text-spredd-green" : "text-spredd-red"
              )}
            >
              {isPositive ? "+" : ""}
              {formatUSD(summary.total_pnl)}
            </p>
            {isPositive ? (
              <TrendingUp className="w-5 h-5 text-spredd-green" />
            ) : (
              <TrendingDown className="w-5 h-5 text-spredd-red" />
            )}
          </div>
          {summary.roi_percent !== 0 && (
            <p
              className={cn(
                "text-xs mt-0.5",
                isPositive ? "text-spredd-green" : "text-spredd-red"
              )}
            >
              {isPositive ? "+" : ""}
              {summary.roi_percent.toFixed(1)}% ROI
            </p>
          )}
        </div>
      </div>

      {/* Stats row */}
      <div className="flex gap-4 mt-3 pt-3 border-t border-border/50">
        <div>
          <p className="text-xs text-muted-foreground">Trades</p>
          <p className="text-sm font-medium text-foreground">
            {summary.total_trades}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Won</p>
          <p className="text-sm font-medium text-spredd-green">
            {summary.winning_trades}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Lost</p>
          <p className="text-sm font-medium text-spredd-red">
            {summary.losing_trades}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Invested</p>
          <p className="text-sm font-medium text-foreground">
            {formatUSD(summary.total_invested)}
          </p>
        </div>
      </div>
    </div>
  );
}
