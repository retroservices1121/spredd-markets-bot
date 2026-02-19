import { ArrowLeft, AlertTriangle } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { PriceBar } from "@/components/markets/PriceBar";
import { OutcomeButton } from "@/components/markets/OutcomeButton";
import { TradePanel } from "@/components/markets/TradePanel";
import { TradeConfirm } from "@/components/markets/TradeConfirm";
import { TradeResult as TradeResultView } from "@/components/markets/TradeResult";
import { useMarketDetail } from "@/hooks/useMarketDetail";
import { useTrade } from "@/hooks/useTrade";
import { useState } from "react";
import { formatUSD } from "@/lib/utils";
import type { Platform } from "@/core/markets";
import { PLATFORMS } from "@/core/markets";

interface MarketDetailPageProps {
  slug: string;
  onBack: () => void;
}

/** Extract platform from composite slug format "platform/market_id" */
function parsePlatformSlug(slug: string): { platform: Platform; slug: string } {
  const parts = slug.split("/");
  if (parts.length >= 2) {
    const maybePlatform = parts[0] as Platform;
    const knownPlatforms: Platform[] = ["polymarket", "kalshi", "opinion", "limitless", "myriad"];
    if (knownPlatforms.includes(maybePlatform)) {
      return { platform: maybePlatform, slug: parts.slice(1).join("/") };
    }
  }
  return { platform: "polymarket", slug };
}

/** Get collateral notice text for a platform */
function getCollateralNotice(platform: Platform): string {
  const meta = PLATFORMS.find((p) => p.id === platform);
  if (!meta) return "";
  if (platform === "kalshi") return "Kalshi uses USDC on Solana (via DFlow)";
  return `${meta.label} uses ${meta.currency} on ${meta.chain}`;
}

export function MarketDetailPage({ slug, onBack }: MarketDetailPageProps) {
  const { platform } = parsePlatformSlug(slug);
  // Pass full slug (with platform prefix) so useMarketDetail can detect the platform
  const { event, loading, error } = useMarketDetail(slug);
  const [showConfirm, setShowConfirm] = useState(false);
  const [marketIndex, setMarketIndex] = useState(0);

  // Get the active market (first or selected)
  const market = event?.markets[marketIndex] ?? null;

  // Pass outcomes and conditionId to trade hook
  const trade = useTrade(market?.outcomes ?? null, market?.conditionId ?? null, platform);

  const yesPrice = market?.outcomes[0]?.price ?? 0.5;
  const noPrice = market?.outcomes[1]?.price ?? 0.5;

  if (loading && !event) {
    return (
      <div className="p-4 space-y-3">
        <button
          onClick={onBack}
          className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="w-4 h-4" />
          Back
        </button>
        <Skeleton className="h-6 w-3/4" />
        <Skeleton className="h-20 w-full rounded-xl" />
        <Skeleton className="h-40 w-full rounded-xl" />
      </div>
    );
  }

  if (error || !event) {
    return (
      <div className="p-4 space-y-3">
        <button
          onClick={onBack}
          className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="w-4 h-4" />
          Back
        </button>
        <p className="text-sm text-spredd-red text-center py-8">
          {error || "Market not found"}
        </p>
      </div>
    );
  }

  return (
    <div className="p-4 space-y-4">
      {/* Back button */}
      <button
        onClick={onBack}
        className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft className="w-4 h-4" />
        Back
      </button>

      {/* Event header */}
      <div className="flex gap-3">
        {event.image && (
          <img
            src={event.image}
            alt=""
            className="w-12 h-12 rounded-xl object-cover flex-shrink-0"
          />
        )}
        <div>
          <h2 className="text-sm font-bold text-foreground leading-tight">
            {event.title}
          </h2>
          <div className="flex items-center gap-3 mt-1">
            <span className="text-xs text-muted-foreground">
              Vol {formatUSD(event.volume)}
            </span>
            {event.category && (
              <span className="text-xs px-1.5 py-0.5 rounded bg-secondary text-muted-foreground">
                {event.category}
              </span>
            )}
            {platform !== "polymarket" && (
              <span className="text-xs px-1.5 py-0.5 rounded bg-spredd-orange/10 text-spredd-orange">
                {PLATFORMS.find((p) => p.id === platform)?.label ?? platform}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Multi-market selector */}
      {event.markets.length > 1 && (
        <div className="space-y-1">
          {event.markets.map((m, i) => (
            <button
              key={m.conditionId}
              onClick={() => {
                setMarketIndex(i);
                trade.reset();
              }}
              className={`w-full text-left p-2 rounded-lg text-xs transition-colors ${
                i === marketIndex
                  ? "bg-spredd-orange/15 text-spredd-orange border border-spredd-orange/30"
                  : "text-muted-foreground hover:text-foreground hover:bg-secondary/50"
              }`}
            >
              {m.question}
            </button>
          ))}
        </div>
      )}

      {/* Market question (for single-market events) */}
      {event.markets.length === 1 && market && market.question !== event.title && (
        <p className="text-xs text-muted-foreground">{market.question}</p>
      )}

      {/* Description */}
      {event.description && (
        <p className="text-xs text-muted-foreground line-clamp-3">
          {event.description}
        </p>
      )}

      {/* Price bar */}
      {market && <PriceBar yesPrice={yesPrice} />}

      {/* Outcome buttons */}
      {market && (
        <div className="flex gap-3">
          <OutcomeButton
            outcome="yes"
            price={yesPrice}
            selected={trade.outcome === "yes"}
            onClick={() => trade.setOutcome("yes")}
          />
          <OutcomeButton
            outcome="no"
            price={noPrice}
            selected={trade.outcome === "no"}
            onClick={() => trade.setOutcome("no")}
          />
        </div>
      )}

      {/* Wallet not linked warning */}
      {trade.outcome && trade.walletLinked === false && (
        <div className="flex items-start gap-2 p-3 rounded-lg bg-spredd-orange/10 border border-spredd-orange/20">
          <AlertTriangle className="w-4 h-4 text-spredd-orange flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-xs font-medium text-spredd-orange">
              Wallet not linked
            </p>
            <p className="text-xs text-muted-foreground mt-0.5">
              Import the same wallet you use in the Spredd Telegram bot to trade.
              Your EVM wallet address must match.
            </p>
          </div>
        </div>
      )}

      {/* Trade panel (show after outcome selection) */}
      {trade.outcome && (
        <TradePanel
          side={trade.side}
          onSideChange={trade.setSide}
          amount={trade.amount}
          onAmountChange={trade.setAmount}
          quote={trade.quote}
          onReview={() => setShowConfirm(true)}
          disabled={trade.executing || trade.walletLinked === false}
          quoteLoading={trade.quoteLoading}
          quoteError={trade.quoteError}
          slippageBps={trade.slippageBps}
          onSlippageChange={trade.setSlippageBps}
          fees={trade.fees}
          priceImpact={trade.priceImpact}
        />
      )}

      {/* Collateral notice */}
      {trade.outcome && (
        <p className="text-xs text-muted-foreground text-center">
          {getCollateralNotice(platform)}
        </p>
      )}

      {/* Confirmation modal */}
      {showConfirm && trade.quote && (
        <TradeConfirm
          quote={trade.quote}
          executing={trade.executing}
          onConfirm={async () => {
            await trade.handleExecute();
            setShowConfirm(false);
          }}
          onCancel={() => setShowConfirm(false)}
          fees={trade.fees}
          priceImpact={trade.priceImpact}
          slippageBps={trade.slippageBps}
        />
      )}

      {/* Trade result */}
      {trade.result && (
        <TradeResultView
          result={trade.result}
          error={trade.error}
          platform={platform}
          onDone={() => {
            trade.reset();
          }}
          onRetry={() => {
            trade.reset();
          }}
        />
      )}
    </div>
  );
}
