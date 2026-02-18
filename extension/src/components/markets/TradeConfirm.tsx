import { cn } from "@/lib/utils";
import { formatUSD } from "@/lib/utils";
import type { TradeQuote } from "@/core/markets";
import { Loader2 } from "lucide-react";

interface TradeConfirmProps {
  quote: TradeQuote;
  executing: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  fees?: Record<string, string> | null;
  priceImpact?: number | null;
  slippageBps?: number;
}

export function TradeConfirm({
  quote,
  executing,
  onConfirm,
  onCancel,
  fees,
  priceImpact,
  slippageBps,
}: TradeConfirmProps) {
  const isBuy = quote.side === "buy";

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 animate-fade-in">
      <div className="w-full max-w-[360px] bg-card border-t border-border rounded-t-2xl p-4 space-y-4 animate-slide-up">
        <h3 className="text-sm font-bold text-foreground text-center">
          Confirm Trade
        </h3>

        {/* Summary */}
        <div className="space-y-2 p-3 rounded-lg bg-secondary/50">
          <div className="flex justify-between text-sm">
            <span className="text-muted-foreground">Side</span>
            <span
              className={
                isBuy ? "text-spredd-green font-medium" : "text-spredd-red font-medium"
              }
            >
              {isBuy ? "Buy" : "Sell"} {quote.outcome.toUpperCase()}
            </span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-muted-foreground">Amount</span>
            <span className="text-foreground">{formatUSD(quote.amount)}</span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-muted-foreground">Avg Price</span>
            <span className="text-foreground">
              {(quote.avgPrice * 100).toFixed(1)}{"\u00A2"}
            </span>
          </div>
          <div className="flex justify-between text-sm">
            <span className="text-muted-foreground">Expected Shares</span>
            <span className="text-foreground">
              {quote.expectedOutput.toFixed(2)}
            </span>
          </div>

          {/* Price impact */}
          {priceImpact != null && (
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">Price Impact</span>
              <span
                className={cn(
                  "font-medium",
                  priceImpact > 2
                    ? "text-spredd-red"
                    : priceImpact > 0.5
                    ? "text-yellow-500"
                    : "text-spredd-green"
                )}
              >
                {priceImpact.toFixed(2)}%
              </span>
            </div>
          )}

          {/* Fee breakdown */}
          {fees &&
            Object.entries(fees).map(([key, value]) => (
              <div key={key} className="flex justify-between text-sm">
                <span className="text-muted-foreground capitalize">
                  {key.replace(/_/g, " ")}
                </span>
                <span className="text-foreground">{value}</span>
              </div>
            ))}

          {/* Slippage */}
          {slippageBps != null && (
            <div className="flex justify-between text-sm">
              <span className="text-muted-foreground">Max Slippage</span>
              <span className="text-foreground">
                {(slippageBps / 100).toFixed(1)}%
              </span>
            </div>
          )}

          <div className="flex justify-between text-sm border-t border-border pt-2">
            <span className="text-muted-foreground">Potential Payout</span>
            <span className="text-spredd-green font-bold">
              {formatUSD(quote.estimatedPayout)}
            </span>
          </div>
        </div>

        <p className="text-xs text-muted-foreground text-center">
          Trade executed via Spredd. Token approvals handled automatically.
        </p>

        {/* Confirm / Cancel */}
        <div className="flex gap-3">
          <button
            onClick={onCancel}
            disabled={executing}
            className="flex-1 h-11 rounded-lg text-sm font-medium border border-border text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={executing}
            className={
              "flex-1 h-11 rounded-lg text-sm font-medium flex items-center justify-center gap-2 disabled:opacity-50 " +
              (isBuy
                ? "bg-spredd-green text-black hover:bg-spredd-green/90"
                : "bg-spredd-red text-white hover:bg-spredd-red/90")
            }
          >
            {executing ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                Submitting...
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
