import { CheckCircle2, XCircle } from "lucide-react";
import type { SwapBridgeResult } from "@/core/swap";

interface SwapResultProps {
  result: SwapBridgeResult;
  onDone: () => void;
  onRetry?: () => void;
}

export function SwapResult({ result, onDone, onRetry }: SwapResultProps) {
  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-end">
      <div className="w-full bg-card rounded-t-2xl p-5 space-y-4 animate-in slide-in-from-bottom">
        <div className="flex flex-col items-center text-center space-y-3">
          {result.success ? (
            <CheckCircle2 className="w-12 h-12 text-green-500" />
          ) : (
            <XCircle className="w-12 h-12 text-destructive" />
          )}

          <h3 className="text-base font-semibold">
            {result.success ? "Success!" : "Failed"}
          </h3>

          <p className="text-sm text-muted-foreground">{result.message}</p>

          {result.tx_hash && (
            <p className="text-xs text-muted-foreground font-mono break-all">
              TX: {result.tx_hash}
            </p>
          )}
        </div>

        <div className="flex gap-3">
          {!result.success && onRetry && (
            <button
              onClick={onRetry}
              className="flex-1 py-2.5 rounded-lg border border-border text-sm font-medium hover:bg-secondary transition-colors"
            >
              Retry
            </button>
          )}
          <button
            onClick={onDone}
            className="flex-1 py-2.5 rounded-lg bg-spredd-orange text-white text-sm font-medium hover:bg-spredd-orange/90 transition-colors"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
