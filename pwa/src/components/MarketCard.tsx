import { type FeedMarket } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SparklineChart } from "@/components/SparklineChart";
import { CreatorInfo } from "@/components/CreatorInfo";
import { FeedActionBar } from "@/components/FeedActionBar";
import { formatPercent, formatVolume, timeUntil, platformLabel } from "@/lib/utils";

interface MarketCardProps {
  market: FeedMarket;
  onTrade: (outcome: "yes" | "no") => void;
  liked: boolean;
  bookmarked: boolean;
  onLike: () => void;
  onBookmark: () => void;
  onComment: () => void;
  onShare: () => void;
}

const PLACEHOLDER_BG =
  "linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 50%, #0f3460 100%)";

function mockSparkline(price: number): number[] {
  const points: number[] = [];
  let val = price * 100;
  for (let i = 0; i < 24; i++) {
    val += (Math.random() - 0.48) * 4;
    val = Math.max(5, Math.min(95, val));
    points.push(val);
  }
  points.push(price * 100);
  return points;
}

export function MarketCard({
  market,
  onTrade,
  liked,
  bookmarked,
  onLike,
  onBookmark,
  onComment,
  onShare,
}: MarketCardProps) {
  const bgStyle = market.image
    ? { backgroundImage: `url(${market.image})`, backgroundSize: "cover", backgroundPosition: "center" }
    : { background: PLACEHOLDER_BG };

  const sparkData = mockSparkline(market.yes_price);

  return (
    <div
      className="relative h-[100dvh] w-full snap-start snap-always flex flex-col justify-end overflow-hidden"
      style={bgStyle}
    >
      {/* Dark gradient overlay */}
      <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/40 to-black/20" />

      {/* Mesh gradient overlay */}
      <div className="absolute inset-0 mesh-gradient-feed opacity-40" />

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

      {/* Action bar — right side */}
      <div className="absolute right-4 bottom-36 z-10">
        <FeedActionBar
          liked={liked}
          bookmarked={bookmarked}
          likeCount={Math.floor(Math.random() * 200) + 10}
          commentCount={Math.floor(Math.random() * 50)}
          onLike={onLike}
          onComment={onComment}
          onShare={onShare}
          onBookmark={onBookmark}
        />
      </div>

      {/* Content area */}
      <div className="relative z-10 px-5 pb-28 space-y-4 max-w-[calc(100%-60px)]">
        {/* Creator info */}
        {market.creator && (
          <CreatorInfo
            username={market.creator.username}
            avatar={market.creator.avatar}
          />
        )}

        {/* Market question */}
        <h2 className="text-2xl font-bold leading-tight text-white drop-shadow-lg">
          {market.title}
        </h2>

        {/* Sparkline + meta row */}
        <div className="flex items-center gap-4">
          <SparklineChart data={sparkData} width={80} height={28} />
          <div className="flex items-center gap-3 text-sm text-white/70">
            {market.volume != null && market.volume > 0 && (
              <span>Vol {formatVolume(market.volume)}</span>
            )}
            {market.end_date && (
              <span>{timeUntil(market.end_date)}</span>
            )}
          </div>
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
