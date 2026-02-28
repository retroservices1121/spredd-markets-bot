import { useNavigate } from "react-router-dom";
import { type FeedMarket } from "@/api/client";
import { formatVolume } from "@/lib/utils";
import { ProgressBar } from "@/components/ui/progress-bar";

interface MarketGridCardProps {
  market: FeedMarket;
}

const PLACEHOLDER_BG =
  "linear-gradient(135deg, rgba(0,217,115,0.1) 0%, rgba(15,15,26,0.8) 100%)";

export function MarketGridCard({ market }: MarketGridCardProps) {
  const navigate = useNavigate();

  return (
    <button
      onClick={() => navigate(`/market/${market.platform}/${market.id}`)}
      className="glass-card overflow-hidden text-left w-full"
    >
      {/* Image */}
      <div
        className="h-[100px] w-full bg-cover bg-center"
        style={
          market.image
            ? { backgroundImage: `url(${market.image})` }
            : { background: PLACEHOLDER_BG }
        }
      />

      {/* Content */}
      <div className="p-3 space-y-2">
        <h3 className="text-xs font-semibold text-white leading-tight line-clamp-2 min-h-[32px]">
          {market.title}
        </h3>
        <ProgressBar yesPercent={market.yes_price * 100} />
        {market.volume != null && market.volume > 0 && (
          <p className="text-[10px] text-white/40">Vol {formatVolume(market.volume)}</p>
        )}
      </div>
    </button>
  );
}
