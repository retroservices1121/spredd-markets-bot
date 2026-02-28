import { useNavigate } from "react-router-dom";
import { ArrowLeft, Search, X, Clock, Loader2, TrendingUp } from "lucide-react";
import { Input } from "@/components/ui/input";
import { MarketGridCard } from "@/components/MarketGridCard";
import { CategoryPills } from "@/components/CategoryPills";
import { useSearch } from "@/hooks/useSearch";
import { useState } from "react";

const FILTER_TAGS = ["All", "Trending", "New", "Ending Soon"];

export function SearchPage() {
  const navigate = useNavigate();
  const { query, setQuery, results, loading, recentSearches, addRecentSearch, clearRecent } = useSearch();
  const [filter, setFilter] = useState("All");

  const handleSearch = (q: string) => {
    setQuery(q);
    addRecentSearch(q);
  };

  return (
    <div className="min-h-[100dvh] bg-spredd-bg pb-24">
      {/* Header */}
      <div className="sticky top-0 z-30 glass-tab-bar px-4 pt-14 pb-3">
        <div className="flex items-center gap-3 mb-3">
          <button
            onClick={() => navigate(-1)}
            className="text-white/60 hover:text-white shrink-0"
          >
            <ArrowLeft size={24} />
          </button>
          <div className="relative flex-1">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-white/40" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && query.trim()) {
                  addRecentSearch(query.trim());
                }
              }}
              placeholder="Search markets..."
              className="pl-9 pr-9 bg-white/6 border-white/10 text-white h-10"
              autoFocus
            />
            {query && (
              <button
                onClick={() => setQuery("")}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-white/40"
              >
                <X size={16} />
              </button>
            )}
          </div>
        </div>

        {/* Filter tabs */}
        <CategoryPills
          categories={FILTER_TAGS}
          selected={filter}
          onSelect={setFilter}
        />
      </div>

      <div className="px-5 pt-4">
        {/* Recent searches — show when no query */}
        {!query && recentSearches.length > 0 && (
          <div className="mb-6">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-medium text-white/50 flex items-center gap-2">
                <Clock size={14} /> Recent
              </h3>
              <button
                onClick={clearRecent}
                className="text-xs text-white/30 hover:text-white/50"
              >
                Clear
              </button>
            </div>
            <div className="flex flex-wrap gap-2">
              {recentSearches.map((s) => (
                <button
                  key={s}
                  onClick={() => handleSearch(s)}
                  className="px-3 py-1.5 rounded-full bg-white/6 text-white/60 text-sm hover:bg-white/10"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Suggestions — show when no query and no recent */}
        {!query && recentSearches.length === 0 && (
          <div className="mb-6">
            <h3 className="text-sm font-medium text-white/50 flex items-center gap-2 mb-3">
              <TrendingUp size={14} /> Popular Searches
            </h3>
            <div className="flex flex-wrap gap-2">
              {["Bitcoin", "Trump", "Fed Rate", "AI", "SpaceX", "Crypto"].map((s) => (
                <button
                  key={s}
                  onClick={() => handleSearch(s)}
                  className="px-3 py-1.5 rounded-full bg-white/6 text-white/60 text-sm hover:bg-white/10"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Loading */}
        {loading && (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="w-6 h-6 animate-spin text-spredd-green" />
          </div>
        )}

        {/* Results grid */}
        {!loading && results.length > 0 && (
          <div className="grid grid-cols-2 gap-3">
            {results.map((market) => (
              <MarketGridCard
                key={`${market.platform}-${market.id}`}
                market={market}
              />
            ))}
          </div>
        )}

        {/* No results */}
        {!loading && query && results.length === 0 && (
          <div className="text-center py-12">
            <p className="text-white/40 text-sm">No markets found for "{query}"</p>
            <p className="text-white/25 text-xs mt-1">Try a different search term</p>
          </div>
        )}
      </div>
    </div>
  );
}
