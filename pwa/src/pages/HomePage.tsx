import { useNavigate } from "react-router-dom";
import { Search, Bell, Loader2, RefreshCw } from "lucide-react";
import { useHome } from "@/hooks/useHome";
import { CategoryPills } from "@/components/CategoryPills";
import { FeaturedCard } from "@/components/FeaturedCard";
import { LiveEventCard } from "@/components/LiveEventCard";
import { MarketGridCard } from "@/components/MarketGridCard";

export function HomePage() {
  const navigate = useNavigate();
  const {
    categories,
    selectedCategory,
    setSelectedCategory,
    featured,
    live,
    markets,
    loading,
    error,
    refresh,
  } = useHome();

  const filteredMarkets =
    selectedCategory === "all"
      ? markets
      : markets.filter(
          (m) => m.category?.toLowerCase() === selectedCategory.toLowerCase()
        );

  return (
    <div className="min-h-[100dvh] bg-spredd-bg pb-24">
      {/* Header */}
      <div className="sticky top-0 z-30 glass-tab-bar px-5 pt-14 pb-3">
        <div className="flex items-center justify-between mb-4">
          <h1 className="font-brand text-2xl text-spredd-green">SPREDD</h1>
          <div className="flex items-center gap-3">
            <button
              onClick={() => navigate("/search")}
              className="text-white/60 hover:text-white"
            >
              <Search size={22} />
            </button>
            <button className="text-white/60 hover:text-white relative">
              <Bell size={22} />
              <span className="absolute -top-0.5 -right-0.5 w-2 h-2 bg-spredd-green rounded-full" />
            </button>
          </div>
        </div>

        {/* Category pills */}
        <CategoryPills
          categories={categories.map((c) => c.name)}
          selected={
            categories.find((c) => c.id === selectedCategory)?.name || "All"
          }
          onSelect={(name) => {
            const cat = categories.find((c) => c.name === name);
            setSelectedCategory(cat?.id || "all");
          }}
        />
      </div>

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="w-8 h-8 animate-spin text-spredd-green" />
        </div>
      )}

      {/* Error */}
      {error && !loading && (
        <div className="flex flex-col items-center justify-center py-20 gap-3">
          <p className="text-white/40">{error}</p>
          <button
            onClick={refresh}
            className="flex items-center gap-2 text-spredd-green text-sm"
          >
            <RefreshCw size={14} /> Retry
          </button>
        </div>
      )}

      {!loading && !error && (
        <div className="px-5 space-y-6 pt-4">
          {/* Featured horizontal scroll */}
          {featured.length > 0 && (
            <section>
              <h2 className="text-lg font-bold text-white mb-3">Featured</h2>
              <div className="flex gap-3 overflow-x-auto hide-scrollbar -mx-5 px-5">
                {featured.map((market) => (
                  <FeaturedCard
                    key={`${market.platform}-${market.id}`}
                    market={market}
                  />
                ))}
              </div>
            </section>
          )}

          {/* Live events */}
          {live.length > 0 && (
            <section>
              <h2 className="text-lg font-bold text-white mb-3">Live Events</h2>
              <div className="space-y-2">
                {live.map((market) => (
                  <LiveEventCard
                    key={`${market.platform}-${market.id}`}
                    market={market}
                  />
                ))}
              </div>
            </section>
          )}

          {/* Market grid */}
          {filteredMarkets.length > 0 && (
            <section>
              <h2 className="text-lg font-bold text-white mb-3">Markets</h2>
              <div className="grid grid-cols-2 gap-3">
                {filteredMarkets.map((market) => (
                  <MarketGridCard
                    key={`${market.platform}-${market.id}`}
                    market={market}
                  />
                ))}
              </div>
            </section>
          )}

          {filteredMarkets.length === 0 && !loading && (
            <div className="text-center py-12">
              <p className="text-white/40">No markets in this category</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
