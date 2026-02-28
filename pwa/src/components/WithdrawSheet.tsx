import { useState } from "react";
import { BottomSheet } from "@/components/ui/bottom-sheet";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { type WalletBalance } from "@/api/client";
import { formatUSD } from "@/lib/utils";

interface WithdrawSheetProps {
  open: boolean;
  onClose: () => void;
  wallets: WalletBalance[];
}

export function WithdrawSheet({ open, onClose, wallets }: WithdrawSheetProps) {
  const [amount, setAmount] = useState("");
  const [destination, setDestination] = useState("");
  const [selectedWallet, setSelectedWallet] = useState(0);

  const wallet = wallets[selectedWallet];
  const totalBalance = wallet?.balances.reduce(
    (sum, b) => sum + (parseFloat(b.usd_value || "0") || 0),
    0
  ) || 0;
  const amountNum = parseFloat(amount) || 0;

  const handleWithdraw = () => {
    // TODO: implement when backend supports it
    onClose();
  };

  return (
    <BottomSheet open={open} onClose={onClose} title="Withdraw">
      <div className="space-y-4 pb-4">
        {/* Wallet selector */}
        {wallets.length > 1 && (
          <div className="flex gap-2">
            {wallets.map((w, i) => (
              <button
                key={w.public_key}
                onClick={() => setSelectedWallet(i)}
                className={`px-3 py-1.5 rounded-full text-xs font-medium transition-all ${
                  selectedWallet === i
                    ? "bg-spredd-green/20 text-spredd-green"
                    : "bg-white/6 text-white/50"
                }`}
              >
                {w.chain_family}
              </button>
            ))}
          </div>
        )}

        {/* Balance display */}
        <div className="glass-card p-4 text-center">
          <p className="text-xs text-white/40 mb-1">Available Balance</p>
          <p className="text-2xl font-bold text-white">{formatUSD(totalBalance)}</p>
        </div>

        {/* Amount */}
        <div>
          <label className="text-xs text-white/50 mb-1 block">Amount</label>
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-white/50">$</span>
            <Input
              type="number"
              inputMode="decimal"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              className="pl-7 bg-white/6 border-white/10 text-white"
              placeholder="0.00"
            />
            <button
              onClick={() => setAmount(String(totalBalance))}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-spredd-green font-medium"
            >
              MAX
            </button>
          </div>
        </div>

        {/* Destination */}
        <div>
          <label className="text-xs text-white/50 mb-1 block">Destination address</label>
          <Input
            value={destination}
            onChange={(e) => setDestination(e.target.value)}
            className="bg-white/6 border-white/10 text-white font-mono text-xs"
            placeholder="0x..."
          />
        </div>

        {/* Confirm */}
        <Button
          size="lg"
          className="w-full"
          disabled={amountNum <= 0 || !destination.trim()}
          onClick={handleWithdraw}
        >
          Withdraw {amountNum > 0 ? formatUSD(amountNum) : ""}
        </Button>
      </div>
    </BottomSheet>
  );
}
