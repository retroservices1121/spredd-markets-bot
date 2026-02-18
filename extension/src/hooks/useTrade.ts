import { useState, useCallback, useMemo, useEffect, useRef } from "react";
import type {
  TradeQuote,
  TradeResult,
  TradeSide,
  OutcomeSelection,
  MarketOutcome,
  Platform,
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

  // Slippage
  slippageBps: number;
  setSlippageBps: (bps: number) => void;

  // Quote
  quote: TradeQuote | null;
  quoteLoading: boolean;
  quoteError: string | null;

  // Fees / impact from bot quote
  fees: Record<string, string> | null;
  priceImpact: number | null;

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
  outcomes: MarketOutcome[] | null,
  marketId: string | null,
  platform: Platform = "polymarket"
): UseTradeReturn {
  const [outcome, setOutcome] = useState<OutcomeSelection | null>(null);
  const [side, setSide] = useState<TradeSide>("buy");
  const [amount, setAmount] = useState("");
  const [slippageBps, setSlippageBps] = useState(100); // 1% default
  const [walletLinked, setWalletLinked] = useState<boolean | null>(null);
  const [checkingLink, setCheckingLink] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [result, setResult] = useState<TradeResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Bot API quote state
  const [botQuote, setBotQuote] = useState<TradeQuote | null>(null);
  const [quoteLoading, setQuoteLoading] = useState(false);
  const [quoteError, setQuoteError] = useState<string | null>(null);
  const [fees, setFees] = useState<Record<string, string> | null>(null);
  const [priceImpact, setPriceImpact] = useState<number | null>(null);

  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

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

  // Instant client-side fallback quote from market prices
  const clientQuote = useMemo(() => {
    if (!outcome || !outcomes) return null;
    const amountNum = parseFloat(amount);
    if (!amountNum || amountNum <= 0) return null;

    const selectedOutcome = outcome === "yes" ? outcomes[0] : outcomes[1];
    if (!selectedOutcome) return null;

    const emptyOrderbook = { bids: [], asks: [], midPrice: 0.5, spread: 0 };
    return calculateQuote(
      emptyOrderbook,
      selectedOutcome.tokenId || marketId || "",
      outcome,
      side,
      amountNum,
      selectedOutcome.price
    );
  }, [outcome, outcomes, amount, side, marketId]);

  // Debounced bot API quote fetch
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);

    // Clear bot quote when inputs change
    setBotQuote(null);
    setQuoteError(null);
    setFees(null);
    setPriceImpact(null);

    if (!outcome || !marketId) return;
    const amountNum = parseFloat(amount);
    if (!amountNum || amountNum <= 0) return;

    setQuoteLoading(true);

    debounceRef.current = setTimeout(async () => {
      try {
        const res = await getTradeQuote({
          platform,
          marketId,
          outcome,
          side,
          amount: amountNum.toFixed(2),
        });

        if (!res.success || !res.data) {
          setQuoteError(res.error ?? "Quote unavailable");
          setQuoteLoading(false);
          return;
        }

        const d = res.data;
        const expectedOutput = parseFloat(d.expected_output) || 0;
        const price = d.price || 0;

        setBotQuote({
          tokenId: d.market_id,
          outcome: outcome,
          side: side,
          amount: amountNum,
          expectedOutput,
          avgPrice: price,
          worstPrice: price,
          estimatedPayout: side === "buy" ? expectedOutput : expectedOutput * price,
          platform: (d.platform as Platform) || platform,
          priceImpact: d.price_impact,
          fees: d.fees,
        });
        setFees(d.fees && Object.keys(d.fees).length > 0 ? d.fees : null);
        setPriceImpact(d.price_impact ?? null);
        setQuoteError(null);
      } catch (e) {
        setQuoteError(e instanceof Error ? e.message : "Quote failed");
      } finally {
        setQuoteLoading(false);
      }
    }, 500);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [outcome, side, amount, marketId, platform]);

  // Use bot quote when available, fall back to client estimate
  const quote = botQuote ?? clientQuote;

  // Execute trade via Bot API
  const handleExecute = useCallback(async () => {
    if (!quote || !marketId || !outcome) return;

    setExecuting(true);
    setError(null);
    setResult(null);

    try {
      const res = await executeTrade({
        platform,
        marketId,
        outcome,
        side,
        amount: quote.amount.toFixed(2),
        slippageBps,
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
  }, [quote, marketId, outcome, side, platform, slippageBps]);

  const reset = useCallback(() => {
    setOutcome(null);
    setSide("buy");
    setAmount("");
    setResult(null);
    setError(null);
    setBotQuote(null);
    setQuoteError(null);
    setFees(null);
    setPriceImpact(null);
  }, []);

  return {
    outcome,
    setOutcome,
    side,
    setSide,
    amount,
    setAmount,
    slippageBps,
    setSlippageBps,
    quote,
    quoteLoading,
    quoteError,
    fees,
    priceImpact,
    walletLinked,
    checkingLink,
    executing,
    result,
    error,
    handleExecute,
    reset,
  };
}
