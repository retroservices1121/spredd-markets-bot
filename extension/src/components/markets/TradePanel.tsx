import { cn } from "@/lib/utils";
import { formatUSD } from "@/lib/utils";
import type { TradeQuote, TradeSide } from "@/core/markets";

interface TradePanelProps {
  side: TradeSide;
  onSideChange: (s: TradeSide) => void;
  amount: string;
  onAmountChange: (a: string) => void;
  quote: TradeQuote | null;
  onReview: () => void;
  disabled: boolean;
}

const QUICK_AMOUNTS = [1, 5, 10, 25];

export function TradePanel({
  side,
  onSideChange,
  amount,
  onAmountChange,
  quote,
  onReview,
  disabled,
}: TradePanelProps) {
  return (
    <div className="space-y-3">
      {/* Buy / Sell toggle */}
      <div className="flex rounded-lg overflow-hidden border border-border">
        <button
          onClick={() => onSideChange("buy")}
          className={cn(
            "flex-1 py-2 text-sm font-medium transition-colors",
            side === "buy"
              ? "bg-spredd-green/20 text-spredd-green"
              : "text-muted-foreground hover:text-foreground"
          )}
        >
          Buy
        </button>
        <button
          onClick={() => onSideChange("sell")}
          className={cn(
            "flex-1 py-2 text-sm font-medium transition-colors",
            side === "sell"
              ? "bg-spredd-red/20 text-spredd-red"
              : "text-muted-foreground hover:text-foreground"
          )}
        >
          Sell
        </button>
      </div>

      {/* Amount input */}
      <div>
        <label className="text-xs text-muted-foreground mb-1 block">
          Amount (USD)
        </label>
        <div className="relative">
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground text-sm">
            $
          </span>
          <input
            type="number"
            value={amount}
            onChange={(e) => onAmountChange(e.target.value)}
            placeholder="0.00"
            min="0"
            step="0.01"
            className="w-full h-11 pl-7 pr-3 rounded-lg border border-input bg-background text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        </div>
      </div>

      {/* Quick-fill buttons */}
      <div className="flex gap-2">
        {QUICK_AMOUNTS.map((a) => (
          <button
            key={a}
            onClick={() => onAmountChange(a.toString())}
            className={cn(
              "flex-1 py-1.5 text-xs rounded-lg border transition-colors",
              amount === a.toString()
                ? "border-spredd-orange text-spredd-orange bg-spredd-orange/10"
                : "border-border text-muted-foreground hover:text-foreground hover:border-foreground/30"
            )}
          >
            ${a}
          </button>
        ))}
      </div>

      {/* Quote preview */}
      {quote && (
        <div className="p-3 rounded-lg bg-secondary/50 space-y-1.5">
          <div className="flex justify-between text-xs">
            <span className="text-muted-foreground">Avg Price</span>
            <span className="text-foreground">
              {(quote.avgPrice * 100).toFixed(1)}¢
            </span>
          </div>
          <div className="flex justify-between text-xs">
            <span className="text-muted-foreground">Shares</span>
            <span className="text-foreground">
              {quote.expectedOutput.toFixed(2)}
            </span>
          </div>
          <div className="flex justify-between text-xs">
            <span className="text-muted-foreground">Potential Payout</span>
            <span className="text-spredd-green font-medium">
              {formatUSD(quote.estimatedPayout)}
            </span>
          </div>
        </div>
      )}

      {/* Review button */}
      <button
        onClick={onReview}
        disabled={disabled || !quote || quote.amount <= 0}
        className={cn(
          "w-full h-11 rounded-lg text-sm font-medium transition-all",
          "disabled:opacity-50 disabled:cursor-not-allowed",
          side === "buy"
            ? "bg-spredd-green text-black hover:bg-spredd-green/90 shadow-lg shadow-spredd-green/20"
            : "bg-spredd-red text-white hover:bg-spredd-red/90 shadow-lg shadow-spredd-red/20"
        )}
      >
        Review Trade
      </button>
    </div>
  );
}
