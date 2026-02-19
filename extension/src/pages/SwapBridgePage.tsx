import { useState } from "react";
import { ArrowLeft, ArrowDownUp } from "lucide-react";
import type { DecryptedVault } from "@/core/types";
import type { SwapMode } from "@/core/swap";
import { useSwap } from "@/hooks/useSwap";
import { SwapChainSelect } from "@/components/swap/SwapChainSelect";
import { SwapTokenSelect } from "@/components/swap/SwapTokenSelect";
import { SwapQuotePreview } from "@/components/swap/SwapQuotePreview";
import { SwapConfirm } from "@/components/swap/SwapConfirm";
import { SwapResult } from "@/components/swap/SwapResult";
import { cn } from "@/lib/utils";

interface SwapBridgePageProps {
  vault: DecryptedVault;
  initialMode: SwapMode;
  onBack: () => void;
}

const QUICK_AMOUNTS = ["10", "25", "50", "100"];

export function SwapBridgePage({ initialMode, onBack }: SwapBridgePageProps) {
  const swap = useSwap(initialMode);
  const [showConfirm, setShowConfirm] = useState(false);

  const handleReview = () => {
    if (swap.quote) setShowConfirm(true);
  };

  const handleConfirm = async () => {
    await swap.handleExecute();
    setShowConfirm(false);
  };

  const handleResultDone = () => {
    swap.reset();
  };

  const handleRetry = () => {
    swap.reset();
  };

  return (
    <div className="p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button
          onClick={onBack}
          className="p-1.5 rounded-lg hover:bg-secondary transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
        </button>
        <h2 className="text-base font-semibold">
          {swap.mode === "swap" ? "Swap" : "Bridge"}
        </h2>
      </div>

      {/* Mode Toggle */}
      <div className="flex rounded-lg bg-secondary p-1">
        <button
          onClick={() => swap.setMode("swap")}
          className={cn(
            "flex-1 py-1.5 text-sm font-medium rounded-md transition-colors",
            swap.mode === "swap"
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground"
          )}
        >
          Swap
        </button>
        <button
          onClick={() => swap.setMode("bridge")}
          className={cn(
            "flex-1 py-1.5 text-sm font-medium rounded-md transition-colors",
            swap.mode === "bridge"
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground"
          )}
        >
          Bridge
        </button>
      </div>

      {/* From Section */}
      <div className="rounded-xl bg-secondary/30 border border-border p-3 space-y-3">
        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
          From
        </p>

        <div className="flex gap-2">
          <SwapChainSelect
            label="Chain"
            selected={swap.fromChain}
            onChange={swap.setFromChain}
          />
          {swap.mode === "swap" ? (
            <SwapTokenSelect
              chainId={swap.fromChain}
              selected={swap.fromToken}
              onChange={swap.setFromToken}
            />
          ) : (
            <div className="flex-1">
              <label className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-1 block">
                Token
              </label>
              <div className="w-full px-3 py-2 rounded-lg bg-secondary text-sm text-muted-foreground">
                USDC
              </div>
            </div>
          )}
        </div>

        {/* Amount Input */}
        <div>
          <label className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-1 block">
            Amount
          </label>
          <input
            type="text"
            inputMode="decimal"
            placeholder="0.00"
            value={swap.amount}
            onChange={(e) => {
              const val = e.target.value;
              if (/^\d*\.?\d*$/.test(val)) {
                swap.setAmount(val);
              }
            }}
            className="w-full px-3 py-2.5 rounded-lg bg-secondary text-sm font-medium placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-spredd-orange"
          />

          {/* Quick fill buttons */}
          <div className="flex gap-2 mt-2">
            {QUICK_AMOUNTS.map((qa) => (
              <button
                key={qa}
                onClick={() => swap.setAmount(qa)}
                className={cn(
                  "flex-1 py-1 rounded-md text-xs font-medium transition-colors",
                  swap.amount === qa
                    ? "bg-spredd-orange/20 text-spredd-orange border border-spredd-orange/30"
                    : "bg-secondary text-muted-foreground hover:text-foreground"
                )}
              >
                {swap.mode === "bridge" ? `$${qa}` : qa}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Arrow indicator */}
      <div className="flex justify-center">
        <div className="p-2 rounded-full bg-secondary">
          <ArrowDownUp className="w-4 h-4 text-muted-foreground" />
        </div>
      </div>

      {/* To Section */}
      <div className="rounded-xl bg-secondary/30 border border-border p-3 space-y-3">
        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
          To
        </p>

        <div className="flex gap-2">
          {swap.mode === "bridge" ? (
            <>
              <div className="flex-1">
                <label className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-1 block">
                  Chain
                </label>
                <div className="w-full px-3 py-2 rounded-lg bg-secondary text-sm text-muted-foreground">
                  Polygon
                </div>
              </div>
              <div className="flex-1">
                <label className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-1 block">
                  Token
                </label>
                <div className="w-full px-3 py-2 rounded-lg bg-secondary text-sm text-muted-foreground">
                  USDC
                </div>
              </div>
            </>
          ) : (
            <>
              <div className="flex-1">
                <label className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-1 block">
                  Chain
                </label>
                <div className="w-full px-3 py-2 rounded-lg bg-secondary text-sm text-muted-foreground">
                  {swap.fromChain.charAt(0).toUpperCase() + swap.fromChain.slice(1)}
                </div>
              </div>
              <div className="flex-1">
                <label className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-1 block">
                  Token
                </label>
                <div className="w-full px-3 py-2 rounded-lg bg-secondary text-sm text-muted-foreground">
                  USDC
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Bridge Speed Toggle (bridge mode only) */}
      {swap.mode === "bridge" && (
        <div className="flex rounded-lg bg-secondary p-1">
          <button
            onClick={() => swap.setBridgeSpeed("fast")}
            className={cn(
              "flex-1 py-1.5 text-xs font-medium rounded-md transition-colors",
              swap.bridgeSpeed === "fast"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            Fast (~30s)
          </button>
          <button
            onClick={() => swap.setBridgeSpeed("standard")}
            className={cn(
              "flex-1 py-1.5 text-xs font-medium rounded-md transition-colors",
              swap.bridgeSpeed === "standard"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            Standard (~15min)
          </button>
        </div>
      )}

      {/* Quote Preview */}
      <SwapQuotePreview
        quote={swap.quote}
        loading={swap.quoteLoading}
        error={swap.quoteError}
      />

      {/* Review Button */}
      <button
        onClick={handleReview}
        disabled={!swap.quote || swap.quoteLoading}
        className="w-full py-3 rounded-xl bg-spredd-orange text-white text-sm font-semibold hover:bg-spredd-orange/90 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
      >
        Review {swap.mode === "swap" ? "Swap" : "Bridge"}
      </button>

      {/* Confirm Modal */}
      {showConfirm && swap.quote && (
        <SwapConfirm
          quote={swap.quote}
          executing={swap.executing}
          onConfirm={handleConfirm}
          onCancel={() => setShowConfirm(false)}
        />
      )}

      {/* Result Modal */}
      {swap.result && (
        <SwapResult
          result={swap.result}
          onDone={handleResultDone}
          onRetry={handleRetry}
        />
      )}
    </div>
  );
}
