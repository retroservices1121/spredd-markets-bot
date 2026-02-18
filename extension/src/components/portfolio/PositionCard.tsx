import { cn } from "@/lib/utils";
import { formatUSD } from "@/lib/utils";
import type { Position } from "@/core/markets";
import { PLATFORMS } from "@/core/markets";

interface PositionCardProps {
  position: Position;
}

export function PositionCard({ position }: PositionCardProps) {
  const isPositive = position.pnl >= 0;
  const pnlPercent =
    position.entry_price > 0
      ? ((position.current_price - position.entry_price) / position.entry_price) * 100
      : 0;

  const platformLabel =
    PLATFORMS.find((p) => p.id === position.platform)?.label ?? position.platform;

  return (
    <div className="p-3 rounded-xl border border-border bg-card">
      {/* Title + platform badge */}
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm font-medium text-foreground line-clamp-2 leading-tight flex-1">
          {position.market_title}
        </p>
        <span className="text-xs px-1.5 py-0.5 rounded bg-secondary text-muted-foreground flex-shrink-0">
          {platformLabel}
        </span>
      </div>

      {/* Outcome + amounts */}
      <div className="flex items-center gap-2 mt-2">
        <span
          className={cn(
            "text-xs font-medium px-2 py-0.5 rounded",
            position.outcome.toLowerCase() === "yes"
              ? "bg-spredd-green/15 text-spredd-green"
              : "bg-spredd-red/15 text-spredd-red"
          )}
        >
          {position.outcome}
        </span>
        <span className="text-xs text-muted-foreground">
          {position.token_amount.toFixed(2)} shares
        </span>
      </div>

      {/* Price + P&L row */}
      <div className="flex items-center justify-between mt-2 pt-2 border-t border-border/50">
        <div className="flex gap-3">
          <div>
            <p className="text-xs text-muted-foreground">Entry</p>
            <p className="text-xs font-medium text-foreground">
              {(position.entry_price * 100).toFixed(1)}{"\u00A2"}
            </p>
          </div>
          <div>
            <p className="text-xs text-muted-foreground">Current</p>
            <p className="text-xs font-medium text-foreground">
              {(position.current_price * 100).toFixed(1)}{"\u00A2"}
            </p>
          </div>
        </div>
        <div className="text-right">
          <p
            className={cn(
              "text-sm font-bold",
              isPositive ? "text-spredd-green" : "text-spredd-red"
            )}
          >
            {isPositive ? "+" : ""}
            {formatUSD(position.pnl)}
          </p>
          <p
            className={cn(
              "text-xs",
              isPositive ? "text-spredd-green" : "text-spredd-red"
            )}
          >
            {isPositive ? "+" : ""}
            {pnlPercent.toFixed(1)}%
          </p>
        </div>
      </div>
    </div>
  );
}
