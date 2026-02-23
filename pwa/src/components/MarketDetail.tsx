import { motion } from "framer-motion";
import { X, TrendingUp, Clock, BarChart3 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PriceChart } from "./PriceChart";
import { formatPercent, formatVolume, timeUntil, platformLabel } from "@/lib/utils";
import { type FeedMarket } from "@/api/client";

interface MarketDetailProps {
  market: FeedMarket;
  onTrade: (outcome: "yes" | "no") => void;
  onClose: () => void;
}

export function MarketDetail({ market, onTrade, onClose }: MarketDetailProps) {
  return (
    <motion.div
      className="fixed inset-0 z-50 bg-spredd-black overflow-y-auto"
      initial={{ x: "100%" }}
      animate={{ x: 0 }}
      exit={{ x: "100%" }}
      transition={{ type: "spring", damping: 25, stiffness: 300 }}
    >
      {/* Header */}
      <div className="sticky top-0 z-10 flex items-center justify-between px-4 py-3 bg-spredd-black/90 backdrop-blur-lg">
        <Badge variant="platform">{platformLabel(market.platform)}</Badge>
        <button onClick={onClose} className="text-white/50 hover:text-white">
          <X size={22} />
        </button>
      </div>

      {/* Image */}
      {market.image && (
        <div className="w-full h-48 overflow-hidden">
          <img
            src={market.image}
            alt=""
            className="w-full h-full object-cover"
          />
        </div>
      )}

      <div className="px-5 py-4 space-y-5">
        {/* Title */}
        <h1 className="text-xl font-bold text-white leading-tight">
          {market.title}
        </h1>

        {/* Stats row */}
        <div className="flex items-center gap-4 text-sm text-white/60">
          {market.volume != null && market.volume > 0 && (
            <div className="flex items-center gap-1">
              <BarChart3 size={14} />
              <span>{formatVolume(market.volume)}</span>
            </div>
          )}
          {market.end_date && (
            <div className="flex items-center gap-1">
              <Clock size={14} />
              <span>{timeUntil(market.end_date)}</span>
            </div>
          )}
          {market.category && (
            <Badge variant="secondary" className="text-xs">
              {market.category}
            </Badge>
          )}
        </div>

        {/* Price bars */}
        <div className="space-y-2">
          <div className="flex items-center gap-3">
            <span className="text-sm text-white/60 w-8">Yes</span>
            <div className="flex-1 h-8 bg-spredd-surface rounded-lg overflow-hidden relative">
              <div
                className="h-full bg-spredd-green/30 rounded-lg"
                style={{ width: `${market.yes_price * 100}%` }}
              />
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-sm font-bold text-spredd-green">
                {formatPercent(market.yes_price)}
              </span>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-sm text-white/60 w-8">No</span>
            <div className="flex-1 h-8 bg-spredd-surface rounded-lg overflow-hidden relative">
              <div
                className="h-full bg-spredd-red/30 rounded-lg"
                style={{ width: `${market.no_price * 100}%` }}
              />
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-sm font-bold text-spredd-red">
                {formatPercent(market.no_price)}
              </span>
            </div>
          </div>
        </div>

        {/* Chart */}
        <div>
          <div className="flex items-center gap-2 mb-2">
            <TrendingUp size={14} className="text-white/50" />
            <span className="text-sm text-white/50">Price History</span>
          </div>
          <div className="bg-spredd-surface rounded-xl p-2">
            <PriceChart color={market.yes_price >= 0.5 ? "#00FF88" : "#FF4757"} />
          </div>
        </div>

        {/* Trade buttons */}
        <div className="flex gap-3 pb-6">
          <Button
            variant="yes"
            size="lg"
            className="flex-1"
            onClick={() => onTrade("yes")}
          >
            Buy Yes {formatPercent(market.yes_price)}
          </Button>
          <Button
            variant="no"
            size="lg"
            className="flex-1"
            onClick={() => onTrade("no")}
          >
            Buy No {formatPercent(market.no_price)}
          </Button>
        </div>
      </div>
    </motion.div>
  );
}
