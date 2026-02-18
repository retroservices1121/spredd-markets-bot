import type { TradeResult as TradeResultType } from "@/core/markets";
import { CheckCircle2, XCircle, RotateCcw } from "lucide-react";

interface TradeResultProps {
  result: TradeResultType;
  error: string | null;
  onDone: () => void;
  onRetry: () => void;
}

export function TradeResult({ result, error, onDone, onRetry }: TradeResultProps) {
  const success = result.success && !error;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 animate-fade-in">
      <div className="w-[320px] bg-card border border-border rounded-2xl p-6 space-y-4 text-center animate-slide-up">
        {success ? (
          <>
            <CheckCircle2 className="w-12 h-12 text-spredd-green mx-auto" />
            <h3 className="text-lg font-bold text-foreground">
              Trade Submitted
            </h3>
            <p className="text-sm text-muted-foreground">
              Your order has been submitted to the Polymarket CLOB.
            </p>
            {result.orderId && (
              <p className="text-xs text-muted-foreground break-all">
                Order: {result.orderId}
              </p>
            )}
          </>
        ) : (
          <>
            <XCircle className="w-12 h-12 text-spredd-red mx-auto" />
            <h3 className="text-lg font-bold text-foreground">Trade Failed</h3>
            <p className="text-sm text-spredd-red">
              {error || result.errorMessage || "Unknown error occurred"}
            </p>
          </>
        )}

        <div className="flex gap-3 pt-2">
          {!success && (
            <button
              onClick={onRetry}
              className="flex-1 h-11 rounded-lg text-sm font-medium border border-border text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors flex items-center justify-center gap-2"
            >
              <RotateCcw className="w-4 h-4" />
              Retry
            </button>
          )}
          <button
            onClick={onDone}
            className="flex-1 h-11 rounded-lg text-sm font-medium bg-spredd-orange text-white hover:bg-spredd-orange/90"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
