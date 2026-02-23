import { useState, useCallback, useEffect, useRef } from "react";
import {
  getQuote,
  executeTrade,
  type QuoteResponse,
  type TradeResponse,
} from "@/api/client";

interface UseTradeReturn {
  outcome: "yes" | "no" | null;
  setOutcome: (o: "yes" | "no") => void;
  amount: string;
  setAmount: (a: string) => void;
  quote: QuoteResponse | null;
  quoteLoading: boolean;
  quoteError: string | null;
  executing: boolean;
  result: TradeResponse | null;
  error: string | null;
  handleExecute: () => Promise<void>;
  reset: () => void;
}

export function useTrade(
  marketId: string | null,
  platform: string = "polymarket"
): UseTradeReturn {
  const [outcome, setOutcome] = useState<"yes" | "no" | null>(null);
  const [amount, setAmount] = useState("5");
  const [quote, setQuote] = useState<QuoteResponse | null>(null);
  const [quoteLoading, setQuoteLoading] = useState(false);
  const [quoteError, setQuoteError] = useState<string | null>(null);
  const [executing, setExecuting] = useState(false);
  const [result, setResult] = useState<TradeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  // Debounced quote fetch
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    setQuote(null);
    setQuoteError(null);

    if (!outcome || !marketId) return;
    const amountNum = parseFloat(amount);
    if (!amountNum || amountNum <= 0) return;

    setQuoteLoading(true);

    debounceRef.current = setTimeout(async () => {
      try {
        const res = await getQuote({
          platform,
          market_id: marketId,
          outcome,
          side: "buy",
          amount: amountNum.toFixed(2),
        });
        setQuote(res);
        setQuoteError(null);
      } catch (e) {
        setQuoteError(e instanceof Error ? e.message : "Quote failed");
      } finally {
        setQuoteLoading(false);
      }
    }, 400);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [outcome, amount, marketId, platform]);

  const handleExecute = useCallback(async () => {
    if (!marketId || !outcome) return;
    const amountNum = parseFloat(amount);
    if (!amountNum || amountNum <= 0) return;

    setExecuting(true);
    setError(null);
    setResult(null);

    try {
      const res = await executeTrade({
        platform,
        market_id: marketId,
        outcome,
        side: "buy",
        amount: amountNum.toFixed(2),
        slippage_bps: 100,
      });
      setResult(res);
      if (!res.success) {
        setError(res.error || "Trade failed");
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Trade execution failed";
      setError(msg);
      setResult({ success: false, error: msg });
    } finally {
      setExecuting(false);
    }
  }, [marketId, outcome, amount, platform]);

  const reset = useCallback(() => {
    setOutcome(null);
    setAmount("5");
    setQuote(null);
    setQuoteError(null);
    setResult(null);
    setError(null);
  }, []);

  return {
    outcome,
    setOutcome,
    amount,
    setAmount,
    quote,
    quoteLoading,
    quoteError,
    executing,
    result,
    error,
    handleExecute,
    reset,
  };
}
