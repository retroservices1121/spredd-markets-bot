import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft, Share2, Bookmark, Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { GlassCard } from "@/components/ui/glass-card";
import { ProgressBar } from "@/components/ui/progress-bar";
import { PriceChart } from "@/components/PriceChart";
import { TradeSheet } from "@/components/TradeSheet";
import { AnimatePresence } from "framer-motion";
import {
  getMarketDetail,
  type FeedMarket,
} from "@/api/client";
import { formatVolume, timeUntil, platformLabel, formatPercent } from "@/lib/utils";

const TIMEFRAMES = ["1H", "24H", "7D", "30D", "ALL"];

export function MarketDetailPage() {
  const { platform, marketId } = useParams<{ platform: string; marketId: string }>();
  const navigate = useNavigate();
  const [market, setMarket] = useState<FeedMarket | null>(null);
  const [detail, setDetail] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(true);
  const [selectedTimeframe, setSelectedTimeframe] = useState("24H");
  const [tradeOutcome, setTradeOutcome] = useState<"yes" | "no" | null>(null);

  useEffect(() => {
    if (!platform || !marketId) return;
    setLoading(true);
    getMarketDetail(platform, marketId)
      .then((data) => {
        setDetail(data);
        setMarket({
          id: String(data.id || marketId),
          platform: platform,
          title: String(data.title || data.question || ""),
          image: data.image ? String(data.image) : undefined,
          yes_price: Number(data.yes_price ?? 0.5),
          no_price: Number(data.no_price ?? 0.5),
          volume: Number(data.volume ?? 0),
          category: data.category ? String(data.category) : undefined,
          end_date: data.end_date ? String(data.end_date) : undefined,
        });
      })
      .catch(() => {
        // Use a placeholder market so the page isn't blank
        setMarket({
          id: marketId,
          platform: platform,
          title: "Market Details",
          yes_price: 0.5,
          no_price: 0.5,
        });
      })
      .finally(() => setLoading(false));
  }, [platform, marketId]);

  if (loading) {
    return (
      <div className="h-[100dvh] flex items-center justify-center bg-spredd-bg">
        <Loader2 className="w-8 h-8 animate-spin text-spredd-green" />
      </div>
    );
  }

  if (!market) return null;

  const description = detail.description ? String(detail.description) : null;

  return (
    <>
      <div className="min-h-[100dvh] bg-spredd-bg pb-32">
        {/* Sticky header */}
        <div className="sticky top-0 z-30 glass-tab-bar px-4 pt-14 pb-3 flex items-center justify-between">
          <button onClick={() => navigate(-1)} className="text-white/60 hover:text-white">
            <ArrowLeft size={24} />
          </button>
          <Badge variant="platform">{platformLabel(market.platform)}</Badge>
          <div className="flex items-center gap-2">
            <button className="text-white/60 hover:text-white">
              <Bookmark size={20} />
            </button>
            <button className="text-white/60 hover:text-white">
              <Share2 size={20} />
            </button>
          </div>
        </div>

        {/* Hero image */}
        {market.image && (
          <div
            className="w-full h-48 bg-cover bg-center"
            style={{ backgroundImage: `url(${market.image})` }}
          >
            <div className="w-full h-full bg-gradient-to-b from-transparent to-spredd-bg" />
          </div>
        )}

        <div className="px-5 space-y-5 pt-4">
          {/* Title */}
          <h1 className="text-2xl font-bold text-white leading-tight">
            {market.title}
          </h1>

          {/* Stats row */}
          <div className="flex items-center gap-4 text-sm text-white/50">
            {market.category && <span>{market.category}</span>}
            {market.volume != null && market.volume > 0 && (
              <span>Vol {formatVolume(market.volume)}</span>
            )}
            {market.end_date && <span>{timeUntil(market.end_date)}</span>}
          </div>

          {/* Probability bars */}
          <GlassCard>
            <ProgressBar yesPercent={market.yes_price * 100} />
            <div className="flex justify-between mt-3">
              <div className="text-center">
                <p className="text-2xl font-bold text-spredd-green">
                  {formatPercent(market.yes_price)}
                </p>
                <p className="text-xs text-white/40">Yes</p>
              </div>
              <div className="text-center">
                <p className="text-2xl font-bold text-spredd-red">
                  {formatPercent(market.no_price)}
                </p>
                <p className="text-xs text-white/40">No</p>
              </div>
            </div>
          </GlassCard>

          {/* Price chart */}
          <GlassCard className="p-0 overflow-hidden">
            <div className="flex gap-1 p-3 pb-0">
              {TIMEFRAMES.map((tf) => (
                <button
                  key={tf}
                  onClick={() => setSelectedTimeframe(tf)}
                  className={`px-3 py-1 rounded-full text-xs font-medium transition-all ${
                    selectedTimeframe === tf
                      ? "bg-spredd-green/20 text-spredd-green"
                      : "text-white/40 hover:text-white/60"
                  }`}
                >
                  {tf}
                </button>
              ))}
            </div>
            <div className="h-[200px]">
              <PriceChart />
            </div>
          </GlassCard>

          {/* Description */}
          {description && (
            <GlassCard>
              <h3 className="text-sm font-semibold text-white mb-2">About</h3>
              <p className="text-sm text-white/60 leading-relaxed">
                {description}
              </p>
            </GlassCard>
          )}
        </div>
      </div>

      {/* Fixed bottom trade buttons */}
      <div className="fixed bottom-0 left-0 right-0 z-40 glass-tab-bar px-5 py-4 pb-[calc(1rem+env(safe-area-inset-bottom))]">
        <div className="flex gap-3 max-w-lg mx-auto">
          <Button
            variant="yes"
            size="lg"
            className="flex-1"
            onClick={() => setTradeOutcome("yes")}
          >
            Buy Yes {formatPercent(market.yes_price)}
          </Button>
          <Button
            variant="no"
            size="lg"
            className="flex-1"
            onClick={() => setTradeOutcome("no")}
          >
            Buy No {formatPercent(market.no_price)}
          </Button>
        </div>
      </div>

      {/* Trade Sheet */}
      <AnimatePresence>
        {tradeOutcome && (
          <TradeSheet
            market={market}
            initialOutcome={tradeOutcome}
            onClose={() => setTradeOutcome(null)}
          />
        )}
      </AnimatePresence>
    </>
  );
}
