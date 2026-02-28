import { useNavigate } from "react-router-dom";
import { type FeedMarket } from "@/api/client";
import { formatPercent, timeUntil } from "@/lib/utils";
import { SparklineChart } from "@/components/SparklineChart";

interface LiveEventCardProps {
  market: FeedMarket;
}

// Generate a mock sparkline from the price
function mockSparkline(price: number): number[] {
  const points: number[] = [];
  let val = price * 100;
  for (let i = 0; i < 20; i++) {
    val += (Math.random() - 0.48) * 5;
    val = Math.max(5, Math.min(95, val));
    points.push(val);
  }
  // End near the actual price
  points.push(price * 100);
  return points;
}

export function LiveEventCard({ market }: LiveEventCardProps) {
  const navigate = useNavigate();
  const sparkData = mockSparkline(market.yes_price);
  const trending = sparkData[sparkData.length - 1] > sparkData[0];

  return (
    <button
      onClick={() => navigate(`/market/${market.platform}/${market.id}`)}
      className="flex items-center gap-3 w-full px-4 py-3 glass-card text-left"
    >
      {/* Live dot */}
      <div className="shrink-0">
        <span className="relative flex h-2.5 w-2.5">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-spredd-green opacity-75" />
          <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-spredd-green" />
        </span>
      </div>

      {/* Title + time */}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-white truncate">{market.title}</p>
        {market.end_date && (
          <p className="text-xs text-white/40">{timeUntil(market.end_date)}</p>
        )}
      </div>

      {/* Sparkline */}
      <SparklineChart
        data={sparkData}
        width={60}
        height={24}
        color={trending ? "#00D973" : "#FF4059"}
      />

      {/* Probability */}
      <span className="text-sm font-bold text-spredd-green shrink-0">
        {formatPercent(market.yes_price)}
      </span>
    </button>
  );
}
