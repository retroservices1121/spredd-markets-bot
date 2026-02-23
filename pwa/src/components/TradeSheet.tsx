import { motion, AnimatePresence } from "framer-motion";
import { X, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatUSD, formatPercent } from "@/lib/utils";
import { type FeedMarket } from "@/api/client";
import { useTrade } from "@/hooks/useTrade";
import { TradeConfirm } from "./TradeConfirm";

interface TradeSheetProps {
  market: FeedMarket;
  initialOutcome: "yes" | "no";
  onClose: () => void;
}

const PRESETS = ["1", "5", "10", "25"];

export function TradeSheet({ market, initialOutcome, onClose }: TradeSheetProps) {
  const {
    outcome,
    setOutcome,
    amount,
    setAmount,
    quote,
    quoteLoading,
    executing,
    result,
    error,
    handleExecute,
    reset,
  } = useTrade(market.id, market.platform);

  // Set initial outcome on mount
  if (!outcome) {
    setOutcome(initialOutcome);
  }

  const currentOutcome = outcome || initialOutcome;
  const isYes = currentOutcome === "yes";
  const price = isYes ? market.yes_price : market.no_price;
  const amountNum = parseFloat(amount) || 0;
  const expectedShares = quote
    ? parseFloat(quote.expected_output)
    : amountNum > 0
    ? amountNum / price
    : 0;
  const expectedPayout = expectedShares;

  // Show result overlay
  if (result) {
    return (
      <TradeConfirm
        result={result}
        market={market}
        outcome={currentOutcome}
        amount={amount}
        onClose={() => {
          reset();
          onClose();
        }}
      />
    );
  }

  return (
    <AnimatePresence>
      <motion.div
        className="fixed inset-0 z-50 flex items-end"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
      >
        {/* Backdrop */}
        <div className="absolute inset-0 bg-black/60" onClick={onClose} />

        {/* Sheet */}
        <motion.div
          className="relative w-full bg-spredd-dark rounded-t-2xl pb-8 pt-4 px-5 z-10 max-h-[80vh] overflow-y-auto"
          initial={{ y: "100%" }}
          animate={{ y: 0 }}
          exit={{ y: "100%" }}
          transition={{ type: "spring", damping: 25, stiffness: 300 }}
        >
          {/* Handle + close */}
          <div className="flex items-center justify-between mb-4">
            <div className="w-10 h-1 bg-white/20 rounded-full mx-auto" />
            <button
              onClick={onClose}
              className="absolute top-4 right-4 text-white/50 hover:text-white"
            >
              <X size={20} />
            </button>
          </div>

          {/* Market title */}
          <h3 className="text-lg font-semibold text-white mb-4 pr-8">
            {market.title}
          </h3>

          {/* Outcome toggle */}
          <div className="flex gap-2 mb-5">
            <button
              className={`flex-1 py-2.5 rounded-xl text-sm font-bold transition-all ${
                isYes
                  ? "bg-spredd-green text-black"
                  : "bg-spredd-surface text-white/50"
              }`}
              onClick={() => setOutcome("yes")}
            >
              Yes {formatPercent(market.yes_price)}
            </button>
            <button
              className={`flex-1 py-2.5 rounded-xl text-sm font-bold transition-all ${
                !isYes
                  ? "bg-spredd-red text-white"
                  : "bg-spredd-surface text-white/50"
              }`}
              onClick={() => setOutcome("no")}
            >
              No {formatPercent(market.no_price)}
            </button>
          </div>

          {/* Amount presets */}
          <div className="flex gap-2 mb-3">
            {PRESETS.map((preset) => (
              <button
                key={preset}
                className={`flex-1 py-2 rounded-xl text-sm font-medium transition-all ${
                  amount === preset
                    ? "bg-spredd-orange text-white"
                    : "bg-spredd-surface text-white/70 hover:bg-spredd-surface/80"
                }`}
                onClick={() => setAmount(preset)}
              >
                ${preset}
              </button>
            ))}
          </div>

          {/* Custom amount */}
          <div className="relative mb-5">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-white/50">$</span>
            <Input
              type="number"
              inputMode="decimal"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="pl-7 bg-spredd-surface border-spredd-surface text-white"
              placeholder="Custom amount"
            />
          </div>

          {/* Quote summary */}
          <div className="bg-spredd-surface rounded-xl p-4 mb-5 space-y-2">
            <div className="flex justify-between text-sm">
              <span className="text-white/50">Amount</span>
              <span className="text-white font-medium">
                {formatUSD(amountNum)}
              </span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-white/50">Price</span>
              <span className="text-white font-medium">
                {quoteLoading ? (
                  <Loader2 className="w-4 h-4 animate-spin inline" />
                ) : (
                  formatPercent(quote?.price ?? price)
                )}
              </span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-white/50">Est. shares</span>
              <span className="text-white font-medium">
                {quoteLoading ? (
                  <Loader2 className="w-4 h-4 animate-spin inline" />
                ) : (
                  expectedShares.toFixed(2)
                )}
              </span>
            </div>
            <div className="flex justify-between text-sm border-t border-white/10 pt-2">
              <span className="text-white/50">Potential payout</span>
              <span className={isYes ? "text-spredd-green font-bold" : "text-spredd-red font-bold"}>
                {formatUSD(expectedPayout)}
              </span>
            </div>
          </div>

          {/* Error */}
          {error && (
            <p className="text-spredd-red text-sm mb-3 text-center">{error}</p>
          )}

          {/* Confirm button */}
          <Button
            variant={isYes ? "yes" : "no"}
            size="lg"
            className="w-full text-base"
            disabled={amountNum <= 0 || executing}
            onClick={handleExecute}
          >
            {executing ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                Placing trade...
              </>
            ) : (
              `Buy ${currentOutcome.toUpperCase()} for ${formatUSD(amountNum)}`
            )}
          </Button>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
