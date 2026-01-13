import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search, TrendingUp, Flame, Tag } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import MarketCard from "@/components/markets/MarketCard";
import { useTelegram } from "@/contexts/TelegramContext";
import { searchMarkets, getTrendingMarkets, getCategories, getMarketsByCategory } from "@/lib/api";

export default function MarketsPage() {
  const { initData } = useTelegram();
  const [searchQuery, setSearchQuery] = useState("");
  const [platform, setPlatform] = useState<string>("all");
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null);

  // Fetch categories for Polymarket
  const { data: categoriesData } = useQuery({
    queryKey: ["categories"],
    queryFn: getCategories,
  });

  // Fetch trending markets
  const { data: trendingData, isLoading: trendingLoading } = useQuery({
    queryKey: ["trending-markets", platform],
    queryFn: () =>
      getTrendingMarkets(
        initData,
        platform === "all" ? undefined : platform,
        50
      ),
    enabled: !searchQuery && !selectedCategory,
  });

  // Fetch search results
  const { data: searchData, isLoading: searchLoading } = useQuery({
    queryKey: ["search-markets", searchQuery, platform],
    queryFn: () =>
      searchMarkets(
        initData,
        searchQuery,
        platform === "all" ? undefined : platform,
        50
      ),
    enabled: searchQuery.length >= 2,
  });

  // Fetch category markets
  const { data: categoryData, isLoading: categoryLoading } = useQuery({
    queryKey: ["category-markets", selectedCategory],
    queryFn: () => getMarketsByCategory(initData, selectedCategory!, 50),
    enabled: !!selectedCategory && platform === "polymarket",
  });

  const categories = categoriesData?.categories || [];

  // Determine which markets to show
  let markets;
  let isLoading;

  if (searchQuery) {
    markets = searchData?.markets;
    isLoading = searchLoading;
  } else if (selectedCategory && platform === "polymarket") {
    markets = categoryData?.markets;
    isLoading = categoryLoading;
  } else {
    markets = trendingData?.markets;
    isLoading = trendingLoading;
  }

  // Handle platform change - reset category
  const handlePlatformChange = (newPlatform: string) => {
    setPlatform(newPlatform);
    if (newPlatform !== "polymarket") {
      setSelectedCategory(null);
    }
  };

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
      <Tabs value={platform} onValueChange={handlePlatformChange}>
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

      {/* Category Selector for Polymarket */}
      {platform === "polymarket" && categories.length > 0 && (
        <div className="flex flex-wrap gap-2">
          <Button
            variant={selectedCategory === null ? "default" : "outline"}
            size="sm"
            onClick={() => setSelectedCategory(null)}
            className="text-xs"
          >
            <Flame className="w-3 h-3 mr-1" />
            All
          </Button>
          {categories.map((cat) => (
            <Button
              key={cat.id}
              variant={selectedCategory === cat.id ? "default" : "outline"}
              size="sm"
              onClick={() => setSelectedCategory(cat.id)}
              className="text-xs"
            >
              <span className="mr-1">{cat.emoji}</span>
              {cat.label}
            </Button>
          ))}
        </div>
      )}

      {/* Section Header */}
      <div className="flex items-center gap-2">
        {searchQuery ? (
          <>
            <Search className="w-4 h-4 text-spredd-orange" />
            <span className="text-sm font-medium">
              Results for "{searchQuery}"
            </span>
          </>
        ) : selectedCategory ? (
          <>
            <Tag className="w-4 h-4 text-spredd-orange" />
            <span className="text-sm font-medium">
              {categories.find((c) => c.id === selectedCategory)?.label || selectedCategory} Markets
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
