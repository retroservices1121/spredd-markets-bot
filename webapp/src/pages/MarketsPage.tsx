import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search, TrendingUp, Flame } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import MarketCard from "@/components/markets/MarketCard";
import { useTelegram } from "@/contexts/TelegramContext";
import { searchMarkets, getTrendingMarkets } from "@/lib/api";

export default function MarketsPage() {
  const { initData } = useTelegram();
  const [searchQuery, setSearchQuery] = useState("");
  const [platform, setPlatform] = useState<string>("all");

  // Fetch trending markets
  const { data: trendingData, isLoading: trendingLoading } = useQuery({
    queryKey: ["trending-markets", platform],
    queryFn: () =>
      getTrendingMarkets(
        initData,
        platform === "all" ? undefined : platform,
        20
      ),
    enabled: !searchQuery,
  });

  // Fetch search results
  const { data: searchData, isLoading: searchLoading } = useQuery({
    queryKey: ["search-markets", searchQuery, platform],
    queryFn: () =>
      searchMarkets(
        initData,
        searchQuery,
        platform === "all" ? undefined : platform,
        30
      ),
    enabled: searchQuery.length >= 2,
  });

  const markets = searchQuery ? searchData?.markets : trendingData?.markets;
  const isLoading = searchQuery ? searchLoading : trendingLoading;

  return (
    <div className="p-4 space-y-4">
      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-white/40" />
        <Input
          placeholder="Search markets..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="pl-10 bg-spredd-dark border-border"
        />
      </div>

      {/* Platform Tabs */}
      <Tabs value={platform} onValueChange={setPlatform}>
        <TabsList className="w-full">
          <TabsTrigger value="all" className="flex-1">
            All
          </TabsTrigger>
          <TabsTrigger value="kalshi" className="flex-1">
            Kalshi
          </TabsTrigger>
          <TabsTrigger value="polymarket" className="flex-1">
            Polymarket
          </TabsTrigger>
        </TabsList>
      </Tabs>

      {/* Section Header */}
      <div className="flex items-center gap-2">
        {searchQuery ? (
          <>
            <Search className="w-4 h-4 text-spredd-orange" />
            <span className="text-sm font-medium">
              Results for "{searchQuery}"
            </span>
          </>
        ) : (
          <>
            <Flame className="w-4 h-4 text-spredd-orange" />
            <span className="text-sm font-medium">Trending Markets</span>
          </>
        )}
      </div>

      {/* Markets Grid */}
      {isLoading ? (
        <div className="space-y-3">
          {Array(5)
            .fill(0)
            .map((_, i) => (
              <Skeleton key={i} className="h-32 w-full rounded-xl" />
            ))}
        </div>
      ) : markets && markets.length > 0 ? (
        <div className="space-y-3">
          {markets.map((market, index) => (
            <MarketCard key={market.id} market={market} index={index} />
          ))}
        </div>
      ) : (
        <div className="text-center py-12">
          <TrendingUp className="w-12 h-12 text-white/20 mx-auto mb-3" />
          <p className="text-white/40">
            {searchQuery ? "No markets found" : "No trending markets"}
          </p>
        </div>
      )}
    </div>
  );
}
