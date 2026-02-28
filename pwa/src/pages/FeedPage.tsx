import { useRef, useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";
import { AnimatePresence } from "framer-motion";
import { Loader2, RefreshCw, ArrowLeft } from "lucide-react";
import { useFeed } from "@/hooks/useFeed";
import { MarketCard } from "@/components/MarketCard";
import { TradeSheet } from "@/components/TradeSheet";
import { Skeleton } from "@/components/ui/skeleton";
import { type FeedMarket } from "@/api/client";

export function FeedPage() {
  const navigate = useNavigate();
  const { markets, loading, error, hasMore, loadMore, refresh } = useFeed();
  const scrollRef = useRef<HTMLDivElement>(null);
  const observerRef = useRef<IntersectionObserver | null>(null);

  // Trade sheet state
  const [tradeMarket, setTradeMarket] = useState<FeedMarket | null>(null);
  const [tradeOutcome, setTradeOutcome] = useState<"yes" | "no">("yes");

  // Action bar state (local — optimistic)
  const [likes, setLikes] = useState<Set<string>>(new Set());
  const [bookmarks, setBookmarks] = useState<Set<string>>(new Set());

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

  const marketKey = (m: FeedMarket) => `${m.platform}-${m.id}`;

  const openTrade = (market: FeedMarket, outcome: "yes" | "no") => {
    setTradeMarket(market);
    setTradeOutcome(outcome);
  };

  const toggleLike = (market: FeedMarket) => {
    const key = marketKey(market);
    setLikes((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const toggleBookmark = (market: FeedMarket) => {
    const key = marketKey(market);
    setBookmarks((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const handleShare = async (market: FeedMarket) => {
    const url = `${window.location.origin}/pwa/market/${market.platform}/${market.id}`;
    if (navigator.share) {
      try {
        await navigator.share({ title: market.title, url });
      } catch { /* user cancelled */ }
    } else {
      await navigator.clipboard.writeText(url);
    }
  };

  if (loading && markets.length === 0) {
    return (
      <div className="h-[100dvh] flex flex-col items-center justify-center gap-4 bg-spredd-bg">
        <Loader2 className="w-8 h-8 animate-spin text-spredd-green" />
        <p className="text-white/50">Loading markets...</p>
      </div>
    );
  }

  if (error && markets.length === 0) {
    return (
      <div className="h-[100dvh] flex flex-col items-center justify-center gap-4 px-6 text-center bg-spredd-bg">
        <p className="text-white/50">{error}</p>
        <button
          onClick={refresh}
          className="flex items-center gap-2 text-spredd-green"
        >
          <RefreshCw size={16} /> Try again
        </button>
      </div>
    );
  }

  return (
    <>
      {/* Back button overlay */}
      <button
        onClick={() => navigate(-1)}
        className="fixed top-14 left-4 z-30 w-9 h-9 rounded-full bg-black/30 backdrop-blur-sm flex items-center justify-center text-white/80"
      >
        <ArrowLeft size={18} />
      </button>

      <div
        ref={scrollRef}
        className="h-[100dvh] overflow-y-auto snap-y snap-mandatory hide-scrollbar"
      >
        {markets.map((market, index) => (
          <div
            key={marketKey(market)}
            ref={index === markets.length - 3 ? lastCardRef : undefined}
          >
            <MarketCard
              market={market}
              onTrade={(o) => openTrade(market, o)}
              liked={likes.has(marketKey(market))}
              bookmarked={bookmarks.has(marketKey(market))}
              onLike={() => toggleLike(market)}
              onBookmark={() => toggleBookmark(market)}
              onComment={() => {/* TODO: open comments modal */}}
              onShare={() => handleShare(market)}
            />
          </div>
        ))}

        {/* Loading more indicator */}
        {loading && markets.length > 0 && (
          <div className="h-[100dvh] snap-start flex items-center justify-center">
            <Loader2 className="w-8 h-8 animate-spin text-spredd-green" />
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
              className="flex items-center gap-2 text-spredd-green text-sm"
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
            onClose={() => setTradeMarket(null)}
          />
        )}
      </AnimatePresence>
    </>
  );
}
