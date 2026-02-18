import { ChainSelector } from "@/components/wallet/ChainSelector";
import { AddressBanner } from "@/components/wallet/AddressBanner";
import { BalanceCard } from "@/components/wallet/BalanceCard";
import { TokenRow } from "@/components/wallet/TokenRow";
import { Skeleton } from "@/components/ui/skeleton";
import { useChain } from "@/hooks/useChain";
import { useBalances } from "@/hooks/useBalances";
import type { DecryptedVault } from "@/core/types";

interface WalletPageProps {
  vault: DecryptedVault;
}

export function WalletPage({ vault }: WalletPageProps) {
  const { selected, selectChain } = useChain();
  const { balances, totalUsd, loading, refresh } = useBalances({
    evmAddress: vault.evmAddress,
    solanaAddress: vault.solanaAddress,
    selectedChain: selected,
  });

  return (
    <div className="p-4 space-y-4">
      {/* Chain selector + addresses */}
      <div className="flex items-center justify-between">
        <ChainSelector selected={selected} onChange={selectChain} />
      </div>

      {/* Address banners */}
      <div className="flex flex-wrap gap-2">
        {vault.evmAddress && (
          <AddressBanner address={vault.evmAddress} label="EVM" />
        )}
        {vault.solanaAddress && (
          <AddressBanner address={vault.solanaAddress} label="SOL" />
        )}
      </div>

      {/* Balance card */}
      <BalanceCard totalUsd={totalUsd} loading={loading} onRefresh={refresh} />

      {/* Token list */}
      <div>
        <h3 className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wider">
          Tokens
        </h3>
        {loading && balances.length === 0 ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-14 w-full" />
            ))}
          </div>
        ) : balances.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-8">
            No tokens found on this chain
          </p>
        ) : (
          <div className="divide-y divide-border">
            {balances.map((token) => (
              <TokenRow
                key={`${token.chainId}-${token.symbol}`}
                token={token}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
