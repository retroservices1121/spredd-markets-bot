import { useState, useEffect, useCallback } from "react";
import { fetchAllBalances } from "@/core/balance";
import type { ChainId, TokenBalance } from "@/core/types";

interface UseBalancesOptions {
  evmAddress: string;
  solanaAddress: string;
  selectedChain: ChainId | "all";
}

export function useBalances({
  evmAddress,
  solanaAddress,
  selectedChain,
}: UseBalancesOptions) {
  const [balances, setBalances] = useState<TokenBalance[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (!evmAddress && !solanaAddress) return;
    setLoading(true);
    try {
      const chainIds =
        selectedChain === "all" ? undefined : [selectedChain];
      const results = await fetchAllBalances(
        evmAddress,
        solanaAddress,
        chainIds
      );
      setBalances(results);
    } catch {
      // keep existing balances on error
    } finally {
      setLoading(false);
    }
  }, [evmAddress, solanaAddress, selectedChain]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const totalUsd = balances.reduce((sum, b) => sum + b.usdValue, 0);

  const filteredBalances =
    selectedChain === "all"
      ? [...balances].sort((a, b) => {
          const balA = parseFloat(a.formatted) || 0;
          const balB = parseFloat(b.formatted) || 0;
          // Sort by USD value first, then by raw balance for non-USD tokens
          if (a.usdValue !== b.usdValue) return b.usdValue - a.usdValue;
          return balB - balA;
        })
      : balances.filter((b) => b.chainId === selectedChain);

  return { balances: filteredBalances, totalUsd, loading, refresh };
}
