import { useEffect } from "react";
import { motion } from "framer-motion";
import { CheckCircle, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { formatUSD } from "@/lib/utils";
import { type FeedMarket, type TradeResponse } from "@/api/client";

interface TradeConfirmProps {
  result: TradeResponse;
  market: FeedMarket;
  outcome: "yes" | "no";
  amount: string;
  onClose: () => void;
}

export function TradeConfirm({
  result,
  market,
  outcome,
  amount,
  onClose,
}: TradeConfirmProps) {
  const isSuccess = result.success;
  const isYes = outcome === "yes";

  // Haptic feedback on success
  useEffect(() => {
    if (isSuccess && navigator.vibrate) {
      navigator.vibrate([50, 30, 50]);
    }
  }, [isSuccess]);

  return (
    <motion.div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
    >
      <motion.div
        className="bg-spredd-bg rounded-2xl p-6 mx-6 w-full max-w-sm text-center border border-white/8"
        initial={{ scale: 0.8, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ type: "spring", damping: 20, stiffness: 300 }}
      >
        {/* Animated icon */}
        <motion.div
          className="flex justify-center mb-4"
          initial={{ scale: 0, rotate: -180 }}
          animate={{ scale: 1, rotate: 0 }}
          transition={{ delay: 0.1, type: "spring", damping: 10, stiffness: 200 }}
        >
          {isSuccess ? (
            <div className="w-20 h-20 rounded-full bg-spredd-green/10 flex items-center justify-center">
              <CheckCircle className="w-12 h-12 text-spredd-green" />
            </div>
          ) : (
            <div className="w-20 h-20 rounded-full bg-spredd-red/10 flex items-center justify-center">
              <XCircle className="w-12 h-12 text-spredd-red" />
            </div>
          )}
        </motion.div>

        {/* Title */}
        <h3 className="text-xl font-bold text-white mb-2">
          {isSuccess ? "Trade Placed!" : "Trade Failed"}
        </h3>

        {/* Details */}
        {isSuccess ? (
          <div className="space-y-2 mb-6">
            <p className="text-white/70 text-sm">{market.title}</p>
            <div className="flex items-center justify-center gap-2">
              <span
                className={`px-3 py-1 rounded-full text-sm font-bold ${
                  isYes ? "bg-spredd-green/20 text-spredd-green" : "bg-spredd-red/20 text-spredd-red"
                }`}
              >
                {outcome.toUpperCase()}
              </span>
              <span className="text-white font-medium">
                {formatUSD(amount)}
              </span>
            </div>
            {result.message && (
              <p className="text-white/50 text-xs">{result.message}</p>
            )}
          </div>
        ) : (
          <div className="mb-6">
            <p className="text-white/50 text-sm">
              {result.error || "Something went wrong. Please try again."}
            </p>
          </div>
        )}

        <Button
          variant={isSuccess ? "default" : "outline"}
          size="lg"
          className="w-full"
          onClick={onClose}
        >
          {isSuccess ? "Done" : "Close"}
        </Button>
      </motion.div>
    </motion.div>
  );
}
