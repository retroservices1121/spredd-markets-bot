import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { TrendingUp, Clock } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatPrice, formatNumber, getPlatformName } from "@/lib/utils";
import type { MarketInfo } from "@/lib/api";

interface MarketCardProps {
  market: MarketInfo;
  index?: number;
}

export default function MarketCard({ market, index = 0 }: MarketCardProps) {
  const navigate = useNavigate();

  const handleClick = () => {
    navigate(`/markets/${market.platform}/${market.id}`);
  };

  const platformVariant = market.platform.toLowerCase() as
    | "kalshi"
    | "polymarket"
    | "opinion";

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.05 }}
    >
      <Card
        className="overflow-hidden cursor-pointer hover:border-spredd-orange/50 transition-all hover:shadow-lg hover:shadow-spredd-orange/10"
        onClick={handleClick}
      >
        <CardContent className="p-4">
          {/* Header */}
          <div className="flex items-start justify-between gap-2 mb-3">
            <h3 className="font-medium text-sm leading-tight line-clamp-2 flex-1">
              {market.title}
            </h3>
            <Badge variant={platformVariant} className="shrink-0">
              {getPlatformName(market.platform)}
            </Badge>
          </div>

          {/* Prices */}
          <div className="grid grid-cols-2 gap-2 mb-3">
            <div className="bg-spredd-green/10 rounded-lg p-2 text-center">
              <div className="text-xs text-white/60 mb-1">Yes</div>
              <div className="font-bold text-spredd-green">
                {formatPrice(market.yes_price)}
              </div>
            </div>
            <div className="bg-spredd-red/10 rounded-lg p-2 text-center">
              <div className="text-xs text-white/60 mb-1">No</div>
              <div className="font-bold text-spredd-red">
                {formatPrice(market.no_price)}
              </div>
            </div>
          </div>

          {/* Stats */}
          <div className="flex items-center justify-between text-xs text-white/40">
            <div className="flex items-center gap-1">
              <TrendingUp className="w-3 h-3" />
              <span>${formatNumber(market.volume || "0")} vol</span>
            </div>
            {market.is_active ? (
              <div className="flex items-center gap-1 text-spredd-green">
                <div className="w-1.5 h-1.5 rounded-full bg-spredd-green animate-pulse" />
                <span>Active</span>
              </div>
            ) : (
              <div className="flex items-center gap-1 text-white/40">
                <Clock className="w-3 h-3" />
                <span>Closed</span>
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}
