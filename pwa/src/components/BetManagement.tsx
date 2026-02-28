import { useState } from "react";
import { BottomSheet } from "@/components/ui/bottom-sheet";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { type Position } from "@/api/client";
import { formatUSD, formatPercent } from "@/lib/utils";

interface BetManagementProps {
  position: Position;
  open: boolean;
  onClose: () => void;
  onSell: (amount: number) => void;
}

export function BetManagement({ position, open, onClose, onSell }: BetManagementProps) {
  const [sellPercent, setSellPercent] = useState(100);
  const sellAmount = (position.token_amount * sellPercent) / 100;
  const estimatedReturn = sellAmount * position.current_price;
  const isProfit = position.pnl >= 0;

  return (
    <BottomSheet open={open} onClose={onClose} title="Manage Position">
      <div className="space-y-5 pb-4">
        {/* Position summary */}
        <div className="glass-card p-4 space-y-2">
          <p className="text-sm font-medium text-white">{position.market_title}</p>
          <div className="flex justify-between text-xs text-white/50">
            <span>Outcome</span>
            <span className={
              position.outcome.toLowerCase() === "yes"
                ? "text-spredd-green font-bold"
                : "text-spredd-red font-bold"
            }>
              {position.outcome.toUpperCase()}
            </span>
          </div>
          <div className="flex justify-between text-xs text-white/50">
            <span>Shares</span>
            <span className="text-white">{position.token_amount.toFixed(2)}</span>
          </div>
          <div className="flex justify-between text-xs text-white/50">
            <span>Entry</span>
            <span className="text-white">{formatPercent(position.entry_price)}</span>
          </div>
          <div className="flex justify-between text-xs text-white/50">
            <span>Current</span>
            <span className="text-white">{formatPercent(position.current_price)}</span>
          </div>
          <div className="flex justify-between text-xs border-t border-white/10 pt-2">
            <span className="text-white/50">PnL</span>
            <span className={isProfit ? "text-spredd-green font-bold" : "text-spredd-red font-bold"}>
              {isProfit ? "+" : ""}{formatUSD(position.pnl)}
            </span>
          </div>
        </div>

        {/* Sell slider */}
        <div>
          <p className="text-sm font-medium text-white mb-3">Amount to sell</p>
          <Slider
            min={0}
            max={100}
            step={5}
            value={sellPercent}
            onChange={setSellPercent}
            formatLabel={(v) => `${v}% (${sellAmount.toFixed(2)} shares)`}
          />
        </div>

        {/* Estimated return */}
        <div className="glass-card p-4">
          <div className="flex justify-between text-sm">
            <span className="text-white/50">Estimated return</span>
            <span className="text-white font-bold">{formatUSD(estimatedReturn)}</span>
          </div>
        </div>

        {/* Sell button */}
        <Button
          variant="destructive"
          size="lg"
          className="w-full bg-spredd-red hover:bg-spredd-red/90"
          disabled={sellPercent === 0}
          onClick={() => onSell(sellAmount)}
        >
          Sell {sellPercent}% of Position
        </Button>
      </div>
    </BottomSheet>
  );
}
