import { Loader2, ArrowDown } from "lucide-react";
import type { SwapConfirmQuote } from "@/core/swap";
import { CHAINS } from "@/core/chains";
import type { ChainId } from "@/core/types";

interface SwapConfirmProps {
  quote: SwapConfirmQuote;
  executing: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function SwapConfirm({
  quote,
  executing,
  onConfirm,
  onCancel,
}: SwapConfirmProps) {
  const fromChainConfig = CHAINS[quote.fromChain as ChainId];
  const toChainConfig = CHAINS[quote.toChain as ChainId];
  const outputNum = parseFloat(quote.outputAmount);
  const feeNum = parseFloat(quote.feeAmount);

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-end">
      <div className="w-full bg-card rounded-t-2xl p-5 space-y-4 animate-in slide-in-from-bottom">
        <h3 className="text-base font-semibold text-center">
          Confirm {quote.mode === "swap" ? "Swap" : "Bridge"}
        </h3>

        {/* From → To visual */}
        <div className="space-y-2">
          <div className="rounded-lg bg-secondary p-3 flex items-center justify-between">
            <div>
              <p className="text-xs text-muted-foreground">From</p>
              <p className="text-sm font-medium">
                {quote.inputAmount} {quote.fromToken}
              </p>
            </div>
            <div className="flex items-center gap-1.5">
              {fromChainConfig && (
                <div
                  className="w-2 h-2 rounded-full"
                  style={{ backgroundColor: fromChainConfig.color }}
                />
              )}
              <span className="text-xs text-muted-foreground">
                {fromChainConfig?.name ?? quote.fromChain}
              </span>
            </div>
          </div>

          <div className="flex justify-center">
            <ArrowDown className="w-4 h-4 text-muted-foreground" />
          </div>

          <div className="rounded-lg bg-secondary p-3 flex items-center justify-between">
            <div>
              <p className="text-xs text-muted-foreground">To</p>
              <p className="text-sm font-medium">
                ~{outputNum.toFixed(outputNum < 1 ? 6 : 2)} {quote.toToken}
              </p>
            </div>
            <div className="flex items-center gap-1.5">
              {toChainConfig && (
                <div
                  className="w-2 h-2 rounded-full"
                  style={{ backgroundColor: toChainConfig.color }}
                />
              )}
              <span className="text-xs text-muted-foreground">
                {toChainConfig?.name ?? quote.toChain}
              </span>
            </div>
          </div>
        </div>

        {/* Details */}
        <div className="space-y-1.5 text-xs">
          {feeNum > 0 && (
            <div className="flex justify-between">
              <span className="text-muted-foreground">Fees</span>
              <span>~${feeNum.toFixed(2)} ({quote.feePercent.toFixed(2)}%)</span>
            </div>
          )}
          <div className="flex justify-between">
            <span className="text-muted-foreground">Time</span>
            <span>{quote.estimatedTime}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-muted-foreground">Route</span>
            <span>{quote.toolName}</span>
          </div>
        </div>

        {/* Buttons */}
        <div className="flex gap-3">
          <button
            onClick={onCancel}
            disabled={executing}
            className="flex-1 py-2.5 rounded-lg border border-border text-sm font-medium hover:bg-secondary transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={executing}
            className="flex-1 py-2.5 rounded-lg bg-spredd-orange text-white text-sm font-medium hover:bg-spredd-orange/90 transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {executing ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Processing...
              </>
            ) : (
              "Confirm"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
