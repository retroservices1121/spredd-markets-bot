import { useRef, useCallback, useState } from "react";
import { AnimatePresence } from "framer-motion";
import { Loader2, RefreshCw } from "lucide-react";
import { useFeed } from "@/hooks/useFeed";
import { MarketCard } from "@/components/MarketCard";
import { TradeSheet } from "@/components/TradeSheet";
import { MarketDetail } from "@/components/MarketDetail";
import { Skeleton } from "@/components/ui/skeleton";
import { type FeedMarket } from "@/api/client";

export function FeedPage() {
  const { markets, loading, error, hasMore, loadMore, refresh } = useFeed();
  const scrollRef = useRef<HTMLDivElement>(null);
  const observerRef = useRef<IntersectionObserver | null>(null);

  // Trade sheet state
  const [tradeMarket, setTradeMarket] = useState<FeedMarket | null>(null);
  const [tradeOutcome, setTradeOutcome] = useState<"yes" | "no">("yes");

  // Detail view state
  const [detailMarket, setDetailMarket] = useState<FeedMarket | null>(null);

  // Infinite scroll sentinel
  const lastCardRef = useCallback(
    (node: HTMLDivElement | null) => {
      if (observerRef.current) observerRef.current.disconnect();
      if (!node) return;
      observerRef.current = new IntersectionObserver(
        (entries) => {
          if (entries[0].isIntersecting && hasMore) {
            loadMore();
          }
        },
        { threshold: 0.5 }
      );
      observerRef.current.observe(node);
    },
    [hasMore, loadMore]
  );

  const openTrade = (market: FeedMarket, outcome: "yes" | "no") => {
    setTradeMarket(market);
    setTradeOutcome(outcome);
  };

  const closeTrade = () => {
    setTradeMarket(null);
  };

  if (loading && markets.length === 0) {
    return (
      <div className="h-[100dvh] flex flex-col items-center justify-center gap-4">
        <Loader2 className="w-8 h-8 animate-spin text-spredd-orange" />
        <p className="text-white/50">Loading markets...</p>
      </div>
    );
  }

  if (error && markets.length === 0) {
    return (
      <div className="h-[100dvh] flex flex-col items-center justify-center gap-4 px-6 text-center">
        <p className="text-white/50">{error}</p>
        <button
          onClick={refresh}
          className="flex items-center gap-2 text-spredd-orange"
        >
          <RefreshCw size={16} /> Try again
        </button>
      </div>
    );
  }

  return (
    <>
      <div
        ref={scrollRef}
        className="h-[100dvh] overflow-y-auto snap-y snap-mandatory hide-scrollbar"
      >
        {markets.map((market, index) => (
          <div
            key={`${market.platform}-${market.id}`}
            ref={index === markets.length - 3 ? lastCardRef : undefined}
          >
            <MarketCard market={market} onTrade={(o) => openTrade(market, o)} />
          </div>
        ))}

        {/* Loading more indicator */}
        {loading && markets.length > 0 && (
          <div className="h-[100dvh] snap-start flex items-center justify-center">
            <Loader2 className="w-8 h-8 animate-spin text-spredd-orange" />
          </div>
        )}

        {!hasMore && markets.length > 0 && (
          <div className="h-[100dvh] snap-start flex flex-col items-center justify-center gap-3">
            <p className="text-white/40 text-sm">You've seen all markets</p>
            <button
              onClick={() => {
                refresh();
                scrollRef.current?.scrollTo({ top: 0, behavior: "smooth" });
              }}
              className="flex items-center gap-2 text-spredd-orange text-sm"
            >
              <RefreshCw size={14} /> Back to top
            </button>
          </div>
        )}
      </div>

      {/* Trade Sheet */}
      <AnimatePresence>
        {tradeMarket && (
          <TradeSheet
            market={tradeMarket}
            initialOutcome={tradeOutcome}
            onClose={closeTrade}
          />
        )}
      </AnimatePresence>

      {/* Market Detail */}
      <AnimatePresence>
        {detailMarket && (
          <MarketDetail
            market={detailMarket}
            onTrade={(o) => {
              setDetailMarket(null);
              openTrade(detailMarket, o);
            }}
            onClose={() => setDetailMarket(null)}
          />
        )}
      </AnimatePresence>
    </>
  );
}
