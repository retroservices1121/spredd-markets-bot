import { type FeedMarket } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatPercent, formatVolume, timeUntil, platformLabel } from "@/lib/utils";

interface MarketCardProps {
  market: FeedMarket;
  onTrade: (outcome: "yes" | "no") => void;
}

const PLACEHOLDER_BG =
  "linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%)";

export function MarketCard({ market, onTrade }: MarketCardProps) {
  const bgStyle = market.image
    ? { backgroundImage: `url(${market.image})`, backgroundSize: "cover", backgroundPosition: "center" }
    : { background: PLACEHOLDER_BG };

  return (
    <div
      className="relative h-[100dvh] w-full snap-start snap-always flex flex-col justify-end overflow-hidden"
      style={bgStyle}
    >
      {/* Dark gradient overlay */}
      <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/40 to-black/20" />

      {/* Top badges */}
      <div className="absolute top-14 left-4 right-4 flex items-start justify-between z-10">
        <Badge variant="platform" className="text-xs">
          {platformLabel(market.platform)}
        </Badge>
        {market.category && (
          <Badge variant="platform" className="text-xs">
            {market.category}
          </Badge>
        )}
      </div>

      {/* Content area */}
      <div className="relative z-10 px-5 pb-28 space-y-4">
        {/* Market question */}
        <h2 className="text-2xl font-bold leading-tight text-white drop-shadow-lg">
          {market.title}
        </h2>

        {/* Meta row */}
        <div className="flex items-center gap-3 text-sm text-white/70">
          {market.volume != null && market.volume > 0 && (
            <span>Vol {formatVolume(market.volume)}</span>
          )}
          {market.end_date && (
            <span>{timeUntil(market.end_date)}</span>
          )}
        </div>

        {/* YES / NO buttons */}
        <div className="flex gap-3">
          <Button
            variant="yes"
            size="lg"
            className="flex-1 text-base"
            onClick={() => onTrade("yes")}
          >
            Yes {formatPercent(market.yes_price)}
          </Button>
          <Button
            variant="no"
            size="lg"
            className="flex-1 text-base"
            onClick={() => onTrade("no")}
          >
            No {formatPercent(market.no_price)}
          </Button>
        </div>
      </div>
    </div>
  );
}
