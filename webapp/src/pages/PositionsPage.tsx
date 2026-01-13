import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { BarChart3 } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { useTelegram } from "@/contexts/TelegramContext";
import { getPositions, getPnLSummary } from "@/lib/api";
import { formatUSD, formatPercent, getPlatformName, formatShares } from "@/lib/utils";

export default function PositionsPage() {
  const navigate = useNavigate();
  const { initData } = useTelegram();
  const [status, setStatus] = useState<string>("open");
  const [platform, setPlatform] = useState<string>("all");

  // Fetch positions
  const { data: positionsData, isLoading: positionsLoading } = useQuery({
    queryKey: ["positions", status, platform],
    queryFn: () =>
      getPositions(
        initData,
        platform === "all" ? undefined : platform,
        status
      ),
  });

  // Fetch PnL summary
  const { data: pnlData, isLoading: pnlLoading } = useQuery({
    queryKey: ["pnl-summary"],
    queryFn: () => getPnLSummary(initData),
  });

  const positions = positionsData?.positions || [];
  const summaries = pnlData?.summaries || [];

  // Calculate totals
  const totalPnL = summaries.reduce((sum, s) => sum + s.total_pnl, 0);
  const totalTrades = summaries.reduce((sum, s) => sum + s.total_trades, 0);
  const avgROI =
    summaries.length > 0
      ? summaries.reduce((sum, s) => sum + s.roi_percent, 0) / summaries.length
      : 0;

  return (
    <div className="p-4 space-y-4">
      {/* PnL Summary Card */}
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
      >
        <Card
          className={`border-2 ${
            totalPnL >= 0
              ? "border-spredd-green/30 bg-spredd-green/5"
              : "border-spredd-red/30 bg-spredd-red/5"
          }`}
        >
          <CardContent className="p-6">
            <div className="text-center">
              <p className="text-sm text-white/60 mb-1">Total P&L</p>
              {pnlLoading ? (
                <Skeleton className="h-10 w-32 mx-auto" />
              ) : (
                <div
                  className={`text-3xl font-bold ${
                    totalPnL >= 0 ? "text-spredd-green" : "text-spredd-red"
                  }`}
                >
                  {totalPnL >= 0 ? "+" : ""}
                  {formatUSD(totalPnL)}
                </div>
              )}
            </div>

            <div className="grid grid-cols-2 gap-4 mt-4">
              <div className="text-center">
                <p className="text-xs text-white/40">Total Trades</p>
                <p className="text-lg font-semibold">{totalTrades}</p>
              </div>
              <div className="text-center">
                <p className="text-xs text-white/40">Avg ROI</p>
                <p
                  className={`text-lg font-semibold ${
                    avgROI >= 0 ? "text-spredd-green" : "text-spredd-red"
                  }`}
                >
                  {formatPercent(avgROI)}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      </motion.div>

      {/* Platform Summary */}
      {summaries.length > 0 && (
        <div className="grid grid-cols-2 gap-2">
          {summaries.map((summary) => (
            <Card key={summary.platform} className="bg-spredd-dark">
              <CardContent className="p-3">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs text-white/60">
                    {getPlatformName(summary.platform)}
                  </span>
                  <Badge
                    variant={
                      summary.platform as "kalshi" | "polymarket" | "opinion"
                    }
                    className="text-[10px] px-1.5 py-0"
                  >
                    {summary.total_trades}
                  </Badge>
                </div>
                <p
                  className={`font-semibold ${
                    summary.total_pnl >= 0
                      ? "text-spredd-green"
                      : "text-spredd-red"
                  }`}
                >
                  {summary.total_pnl >= 0 ? "+" : ""}
                  {formatUSD(summary.total_pnl)}
                </p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Filters */}
      <div className="space-y-2">
        <Tabs value={status} onValueChange={setStatus}>
          <TabsList className="w-full">
            <TabsTrigger value="open" className="flex-1">
              Open
            </TabsTrigger>
            <TabsTrigger value="closed" className="flex-1">
              Closed
            </TabsTrigger>
          </TabsList>
        </Tabs>

        <Tabs value={platform} onValueChange={setPlatform}>
          <TabsList className="w-full">
            <TabsTrigger value="all" className="flex-1">
              All
            </TabsTrigger>
            <TabsTrigger value="kalshi" className="flex-1">
              Kalshi
            </TabsTrigger>
            <TabsTrigger value="polymarket" className="flex-1">
              Poly
            </TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      {/* Positions List */}
      <div className="space-y-3">
        <h2 className="text-sm font-medium text-white/60 flex items-center gap-2">
          <BarChart3 className="w-4 h-4" />
          {status === "open" ? "Open Positions" : "Closed Positions"}
        </h2>

        {positionsLoading ? (
          <>
            <Skeleton className="h-24 w-full rounded-xl" />
            <Skeleton className="h-24 w-full rounded-xl" />
          </>
        ) : positions.length > 0 ? (
          positions.map((position, index) => (
            <motion.div
              key={position.id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.05 }}
            >
              <Card
                className="cursor-pointer hover:border-spredd-orange/50 transition-colors"
                onClick={() =>
                  navigate(
                    `/markets/${position.platform}/${position.market_id}`
                  )
                }
              >
                <CardContent className="p-4">
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <p className="text-sm font-medium line-clamp-2 flex-1">
                      {position.market_title}
                    </p>
                    <Badge
                      variant={
                        position.outcome === "yes" ? "success" : "destructive"
                      }
                    >
                      {position.outcome.toUpperCase()}
                    </Badge>
                  </div>

                  <div className="grid grid-cols-3 gap-2 text-center">
                    <div>
                      <p className="text-xs text-white/40">Shares</p>
                      <p className="font-medium">
                        {formatShares(position.token_amount)}
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-white/40">Entry</p>
                      <p className="font-medium">
                        {(position.entry_price * 100).toFixed(0)}¢
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-white/40">P&L</p>
                      <p
                        className={`font-medium ${
                          (position.pnl || 0) >= 0
                            ? "text-spredd-green"
                            : "text-spredd-red"
                        }`}
                      >
                        {position.pnl !== null && position.pnl !== undefined
                          ? formatUSD(position.pnl)
                          : position.current_price !== null
                          ? formatUSD(
                              (position.current_price - position.entry_price) *
                                parseFloat(position.token_amount)
                            )
                          : "-"}
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center justify-between mt-2 pt-2 border-t border-border text-xs text-white/40">
                    <Badge
                      variant={
                        position.platform as
                          | "kalshi"
                          | "polymarket"
                          | "opinion"
                      }
                      className="text-[10px]"
                    >
                      {getPlatformName(position.platform)}
                    </Badge>
                    <span>
                      {new Date(position.created_at).toLocaleDateString()}
                    </span>
                  </div>
                </CardContent>
              </Card>
            </motion.div>
          ))
        ) : (
          <Card>
            <CardContent className="p-8 text-center">
              <BarChart3 className="w-12 h-12 text-white/20 mx-auto mb-3" />
              <p className="text-white/60">No {status} positions</p>
              <Button
                variant="outline"
                className="mt-4"
                onClick={() => navigate("/markets")}
              >
                Explore Markets
              </Button>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}
