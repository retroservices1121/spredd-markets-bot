import { useState } from "react";
import { Copy, Check } from "lucide-react";
import { BottomSheet } from "@/components/ui/bottom-sheet";
import { type WalletBalance } from "@/api/client";

interface DepositSheetProps {
  open: boolean;
  onClose: () => void;
  wallets: WalletBalance[];
}

export function DepositSheet({ open, onClose, wallets }: DepositSheetProps) {
  const [copied, setCopied] = useState<string | null>(null);

  const copy = async (address: string) => {
    await navigator.clipboard.writeText(address);
    setCopied(address);
    setTimeout(() => setCopied(null), 2000);
  };

  return (
    <BottomSheet open={open} onClose={onClose} title="Deposit">
      <div className="space-y-4 pb-4">
        <p className="text-sm text-white/50">
          Send funds to your wallet address below
        </p>

        {wallets.map((w) => (
          <div key={w.public_key} className="glass-card p-4">
            <p className="text-xs text-white/40 mb-2">{w.chain_family}</p>
            <div className="flex items-center gap-2">
              <code className="flex-1 text-sm text-white font-mono break-all">
                {w.public_key}
              </code>
              <button
                onClick={() => copy(w.public_key)}
                className="shrink-0 text-white/50 hover:text-white"
              >
                {copied === w.public_key ? (
                  <Check size={18} className="text-spredd-green" />
                ) : (
                  <Copy size={18} />
                )}
              </button>
            </div>
          </div>
        ))}

        {wallets.length === 0 && (
          <p className="text-white/40 text-sm text-center py-4">
            No wallets available
          </p>
        )}
      </div>
    </BottomSheet>
  );
}
