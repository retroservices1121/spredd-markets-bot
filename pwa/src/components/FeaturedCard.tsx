import { useNavigate } from "react-router-dom";
import { type FeedMarket } from "@/api/client";
import { formatPercent, formatVolume } from "@/lib/utils";
import { ProgressBar } from "@/components/ui/progress-bar";

interface FeaturedCardProps {
  market: FeedMarket;
}

const PLACEHOLDER_BG =
  "linear-gradient(135deg, rgba(0,217,115,0.15) 0%, rgba(15,15,26,1) 100%)";

export function FeaturedCard({ market }: FeaturedCardProps) {
  const navigate = useNavigate();

  return (
    <button
      onClick={() => navigate(`/market/${market.platform}/${market.id}`)}
      className="shrink-0 w-[280px] rounded-2xl overflow-hidden text-left glass-card"
    >
      {/* Image */}
      <div
        className="h-[140px] w-full bg-cover bg-center relative"
        style={
          market.image
            ? { backgroundImage: `url(${market.image})` }
            : { background: PLACEHOLDER_BG }
        }
      >
        <div className="absolute inset-0 bg-gradient-to-t from-black/80 to-transparent" />
        {market.category && (
          <span className="absolute top-3 left-3 text-[10px] font-medium bg-white/15 backdrop-blur-sm text-white px-2 py-0.5 rounded-full">
            {market.category}
          </span>
        )}
      </div>

      {/* Content */}
      <div className="p-3 space-y-2">
        <h3 className="text-sm font-semibold text-white leading-tight line-clamp-2">
          {market.title}
        </h3>
        <ProgressBar yesPercent={market.yes_price * 100} showLabels={false} />
        <div className="flex items-center justify-between text-xs text-white/40">
          <span className="text-spredd-green font-medium">
            {formatPercent(market.yes_price)} Yes
          </span>
          {market.volume != null && market.volume > 0 && (
            <span>Vol {formatVolume(market.volume)}</span>
          )}
        </div>
      </div>
    </button>
  );
}
