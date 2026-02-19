import { Loader2 } from "lucide-react";
import type { SwapConfirmQuote } from "@/core/swap";

interface SwapQuotePreviewProps {
  quote: SwapConfirmQuote | null;
  loading: boolean;
  error: string | null;
}

export function SwapQuotePreview({ quote, loading, error }: SwapQuotePreviewProps) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-4">
        <Loader2 className="w-5 h-5 text-muted-foreground animate-spin" />
        <span className="ml-2 text-sm text-muted-foreground">Fetching quote...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg bg-destructive/10 border border-destructive/20 p-3">
        <p className="text-xs text-destructive">{error}</p>
      </div>
    );
  }

  if (!quote) return null;

  const outputNum = parseFloat(quote.outputAmount);
  const feeNum = parseFloat(quote.feeAmount);

  return (
    <div className="rounded-lg bg-secondary/50 border border-border p-3 space-y-2">
      <div className="flex justify-between text-sm">
        <span className="text-muted-foreground">You receive</span>
        <span className="font-medium">
          ~{outputNum.toFixed(outputNum < 1 ? 6 : 2)} {quote.toToken}
        </span>
      </div>

      {feeNum > 0 && (
        <div className="flex justify-between text-xs">
          <span className="text-muted-foreground">Fees</span>
          <span className="text-muted-foreground">
            ~${feeNum.toFixed(2)} ({quote.feePercent.toFixed(2)}%)
          </span>
        </div>
      )}

      <div className="flex justify-between text-xs">
        <span className="text-muted-foreground">Estimated time</span>
        <span className="text-muted-foreground">{quote.estimatedTime}</span>
      </div>

      <div className="flex justify-between text-xs">
        <span className="text-muted-foreground">Route</span>
        <span className="text-muted-foreground">{quote.toolName}</span>
      </div>

      {quote.bridgeMode && (
        <div className="flex justify-between text-xs">
          <span className="text-muted-foreground">Mode</span>
          <span className="text-muted-foreground capitalize">{quote.bridgeMode}</span>
        </div>
      )}
    </div>
  );
}
