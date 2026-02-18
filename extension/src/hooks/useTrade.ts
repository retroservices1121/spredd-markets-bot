import { useState, useCallback, useMemo, useEffect } from "react";
import type {
  TradeQuote,
  TradeResult,
  TradeSide,
  OutcomeSelection,
  Orderbook,
} from "@/core/markets";
import { calculateQuote } from "@/services/polymarket";
import {
  getTradeQuote,
  executeTrade,
  checkWalletLinked,
} from "@/lib/messaging";

interface UseTradeReturn {
  // Trade setup
  outcome: OutcomeSelection | null;
  setOutcome: (o: OutcomeSelection) => void;
  side: TradeSide;
  setSide: (s: TradeSide) => void;
  amount: string;
  setAmount: (a: string) => void;

  // Quote (client-side estimate from orderbook)
  quote: TradeQuote | null;

  // Wallet link status
  walletLinked: boolean | null;
  checkingLink: boolean;

  // Execution
  executing: boolean;
  result: TradeResult | null;
  error: string | null;
  handleExecute: () => Promise<void>;
  reset: () => void;
}

export function useTrade(
  tokenIds: { yes: string; no: string } | null,
  orderbooks: Record<string, Orderbook>,
  marketId: string | null
): UseTradeReturn {
  const [outcome, setOutcome] = useState<OutcomeSelection | null>(null);
  const [side, setSide] = useState<TradeSide>("buy");
  const [amount, setAmount] = useState("");
  const [walletLinked, setWalletLinked] = useState<boolean | null>(null);
  const [checkingLink, setCheckingLink] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [result, setResult] = useState<TradeResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Check wallet link status once
  useEffect(() => {
    let cancelled = false;
    setCheckingLink(true);
    checkWalletLinked()
      .then((res) => {
        if (!cancelled) {
          setWalletLinked(res.success ? (res.data?.linked ?? false) : false);
        }
      })
      .catch(() => {
        if (!cancelled) setWalletLinked(false);
      })
      .finally(() => {
        if (!cancelled) setCheckingLink(false);
      });
    return () => { cancelled = true; };
  }, []);

  // Calculate client-side quote from orderbook (for preview)
  const quote = useMemo(() => {
    if (!outcome || !tokenIds) return null;
    const amountNum = parseFloat(amount);
    if (!amountNum || amountNum <= 0) return null;

    const tokenId = outcome === "yes" ? tokenIds.yes : tokenIds.no;
    const ob = orderbooks[tokenId];
    if (!ob) return null;

    return calculateQuote(ob, tokenId, outcome, side, amountNum);
  }, [outcome, tokenIds, amount, side, orderbooks]);

  // Execute trade via Bot API
  const handleExecute = useCallback(async () => {
    if (!quote || !marketId || !outcome) return;

    setExecuting(true);
    setError(null);
    setResult(null);

    try {
      // Execute via Bot API (background worker signs auth headers)
      const res = await executeTrade({
        platform: "polymarket",
        marketId,
        outcome,
        side,
        amount: quote.amount.toFixed(2),
      });

      if (!res.success) {
        setError(res.error ?? "Trade failed");
        setResult({ success: false, errorMessage: res.error });
        return;
      }

      setResult({
        success: true,
        orderId: res.data?.order_id,
        txHash: res.data?.tx_hash ?? undefined,
        message: res.data?.message,
      });
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Trade execution failed";
      setError(msg);
      setResult({ success: false, errorMessage: msg });
    } finally {
      setExecuting(false);
    }
  }, [quote, marketId, outcome, side]);

  const reset = useCallback(() => {
    setOutcome(null);
    setSide("buy");
    setAmount("");
    setResult(null);
    setError(null);
  }, []);

  return {
    outcome,
    setOutcome,
    side,
    setSide,
    amount,
    setAmount,
    quote,
    walletLinked,
    checkingLink,
    executing,
    result,
    error,
    handleExecute,
    reset,
  };
}
