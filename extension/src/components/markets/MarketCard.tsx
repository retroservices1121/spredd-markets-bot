import type { PolymarketEvent } from "@/core/markets";
import { PriceBar } from "./PriceBar";
import { formatUSD } from "@/lib/utils";

interface MarketCardProps {
  event: PolymarketEvent;
  onClick: () => void;
}

export function MarketCard({ event, onClick }: MarketCardProps) {
  // Use the first market's outcomes for prices
  const market = event.markets[0];
  const yesPrice = market?.outcomes[0]?.price ?? 0.5;
  const title =
    event.markets.length === 1
      ? market?.question ?? event.title
      : event.title;

  return (
    <button
      onClick={onClick}
      className="w-full text-left p-3 rounded-xl border border-border bg-card hover:bg-secondary/50 transition-colors"
    >
      <div className="flex gap-3">
        {event.image && (
          <img
            src={event.image}
            alt=""
            className="w-10 h-10 rounded-lg object-cover flex-shrink-0"
          />
        )}
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-foreground line-clamp-2 leading-tight">
            {title}
          </p>

          <PriceBar yesPrice={yesPrice} className="mt-2" />

          <div className="flex items-center gap-3 mt-1.5">
            <span className="text-xs text-muted-foreground">
              Vol {formatUSD(event.volume)}
            </span>
            {event.category && (
              <span className="text-xs px-1.5 py-0.5 rounded bg-secondary text-muted-foreground">
                {event.category}
              </span>
            )}
            {event.markets.length > 1 && (
              <span className="text-xs text-muted-foreground">
                {event.markets.length} markets
              </span>
            )}
          </div>
        </div>
      </div>
    </button>
  );
}
