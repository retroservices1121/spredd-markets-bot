import { RefreshCw } from "lucide-react";
import { formatUSD } from "@/lib/utils";

interface BalanceCardProps {
  totalUsd: number;
  loading: boolean;
  onRefresh: () => void;
}

export function BalanceCard({ totalUsd, loading, onRefresh }: BalanceCardProps) {
  return (
    <div className="relative overflow-hidden rounded-xl bg-gradient-to-br from-spredd-orange/20 via-spredd-orange/10 to-transparent border border-spredd-orange/20 p-4">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs text-muted-foreground mb-1">Total Balance</p>
          <p className="text-2xl font-bold text-foreground">
            {loading ? "..." : formatUSD(totalUsd)}
          </p>
        </div>
        <button
          onClick={onRefresh}
          disabled={loading}
          className="p-2 rounded-lg hover:bg-white/10 transition-colors disabled:opacity-50"
        >
          <RefreshCw
            className={`w-4 h-4 text-muted-foreground ${loading ? "animate-spin" : ""}`}
          />
        </button>
      </div>
    </div>
  );
}
