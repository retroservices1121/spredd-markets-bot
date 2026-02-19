import { useState, useCallback, useEffect, useRef } from "react";
import type { ChainId, TokenConfig } from "@/core/types";
import type {
  SwapMode,
  SwapQuoteData,
  BridgeQuoteData,
  SwapConfirmQuote,
  SwapBridgeResult,
  BridgeChainsResponse,
} from "@/core/swap";
import {
  getSwapQuote,
  executeSwap,
  getBridgeQuote,
  executeBridge,
  getBridgeChains,
} from "@/lib/messaging";
import { CHAINS } from "@/core/chains";

interface UseSwapReturn {
  // Mode
  mode: SwapMode;
  setMode: (m: SwapMode) => void;

  // Inputs
  fromChain: ChainId;
  setFromChain: (c: ChainId) => void;
  toChain: ChainId;
  setToChain: (c: ChainId) => void;
  fromToken: TokenConfig | null;
  setFromToken: (t: TokenConfig | null) => void;
  amount: string;
  setAmount: (a: string) => void;
  bridgeSpeed: "fast" | "standard";
  setBridgeSpeed: (s: "fast" | "standard") => void;

  // Bridge chains data
  bridgeChains: BridgeChainsResponse | null;

  // Quote
  quote: SwapConfirmQuote | null;
  quoteLoading: boolean;
  quoteError: string | null;

  // Execution
  executing: boolean;
  result: SwapBridgeResult | null;
  error: string | null;
  handleExecute: () => Promise<void>;
  reset: () => void;
}

export function useSwap(initialMode: SwapMode = "swap"): UseSwapReturn {
  const [mode, setModeRaw] = useState<SwapMode>(initialMode);
  const [fromChain, setFromChain] = useState<ChainId>("polygon");
  const [toChain, setToChain] = useState<ChainId>("polygon");
  const [fromToken, setFromToken] = useState<TokenConfig | null>(null);
  const [amount, setAmount] = useState("");
  const [bridgeSpeed, setBridgeSpeed] = useState<"fast" | "standard">("fast");

  const [bridgeChains, setBridgeChains] = useState<BridgeChainsResponse | null>(null);

  const [quote, setQuote] = useState<SwapConfirmQuote | null>(null);
  const [quoteLoading, setQuoteLoading] = useState(false);
  const [quoteError, setQuoteError] = useState<string | null>(null);

  const [executing, setExecuting] = useState(false);
  const [result, setResult] = useState<SwapBridgeResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  // Auto-detect mode based on chains
  const setMode = useCallback((m: SwapMode) => {
    setModeRaw(m);
    if (m === "swap") {
      setToChain(fromChain);
    }
  }, [fromChain]);

  // When fromChain changes in swap mode, sync toChain
  useEffect(() => {
    if (mode === "swap") {
      setToChain(fromChain);
    }
  }, [fromChain, mode]);

  // When chains diverge, auto-switch to bridge
  useEffect(() => {
    if (fromChain !== toChain && mode === "swap") {
      setModeRaw("bridge");
    } else if (fromChain === toChain && mode === "bridge") {
      setModeRaw("swap");
    }
  }, [fromChain, toChain, mode]);

  // Fetch bridge chains on mount
  useEffect(() => {
    getBridgeChains().then((res) => {
      if (res.success && res.data) {
        setBridgeChains(res.data);
      }
    });
  }, []);

  // Set default from token when chain changes
  useEffect(() => {
    const chainConfig = CHAINS[fromChain];
    if (chainConfig && chainConfig.tokens.length > 0) {
      // Default to the native token for swaps
      const native = chainConfig.tokens.find((t) => t.isNative);
      setFromToken(native || chainConfig.tokens[0]);
    }
  }, [fromChain]);

  // Debounced quote fetch
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);

    setQuote(null);
    setQuoteError(null);

    const amountNum = parseFloat(amount);
    if (!amountNum || amountNum <= 0) return;

    if (mode === "swap" && !fromToken) return;

    setQuoteLoading(true);

    debounceRef.current = setTimeout(async () => {
      try {
        if (mode === "swap") {
          const res = await getSwapQuote({
            chain: fromChain,
            from_token: fromToken?.isNative ? "native" : fromToken?.address || "native",
            from_decimals: fromToken?.decimals || 18,
            amount: amount,
          });

          if (!res.success || !res.data) {
            setQuoteError(res.error ?? "Quote unavailable");
            setQuoteLoading(false);
            return;
          }

          const d = res.data as SwapQuoteData;
          if (!d.available) {
            setQuoteError(d.error ?? "Swap not available");
            setQuoteLoading(false);
            return;
          }

          setQuote({
            mode: "swap",
            fromChain,
            toChain: fromChain,
            fromToken: fromToken?.symbol || "TOKEN",
            toToken: "USDC",
            inputAmount: amount,
            outputAmount: d.output_amount,
            feeAmount: d.fee_amount,
            feePercent: d.fee_percent,
            estimatedTime: d.estimated_time,
            toolName: d.tool_name,
          });
          setQuoteError(null);
        } else {
          // Bridge mode
          const res = await getBridgeQuote({
            source_chain: fromChain,
            amount: amount,
          });

          if (!res.success || !res.data) {
            setQuoteError(res.error ?? "Quote unavailable");
            setQuoteLoading(false);
            return;
          }

          const d = res.data as BridgeQuoteData;
          const selected = bridgeSpeed === "fast" ? d.fast_bridge : d.standard_bridge;

          if (!selected || !selected.available) {
            setQuoteError(
              bridgeSpeed === "fast"
                ? d.fast_bridge?.error ?? "Fast bridge unavailable"
                : "Standard bridge unavailable"
            );
            setQuoteLoading(false);
            return;
          }

          setQuote({
            mode: "bridge",
            fromChain,
            toChain: "polygon",
            fromToken: "USDC",
            toToken: "USDC",
            inputAmount: amount,
            outputAmount: selected.output_amount,
            feeAmount: selected.fee_amount,
            feePercent: selected.fee_percent,
            estimatedTime: selected.estimated_time,
            toolName: bridgeSpeed === "fast" ? "Relay" : "CCTP",
            bridgeMode: bridgeSpeed,
          });
          setQuoteError(null);
        }
      } catch (e) {
        setQuoteError(e instanceof Error ? e.message : "Quote failed");
      } finally {
        setQuoteLoading(false);
      }
    }, 500);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [mode, fromChain, toChain, fromToken, amount, bridgeSpeed]);

  // Execute swap or bridge
  const handleExecute = useCallback(async () => {
    if (!quote) return;

    setExecuting(true);
    setError(null);
    setResult(null);

    try {
      if (mode === "swap") {
        const res = await executeSwap({
          chain: fromChain,
          from_token: fromToken?.isNative ? "native" : fromToken?.address || "native",
          from_decimals: fromToken?.decimals || 18,
          amount,
        });

        if (!res.success) {
          setError(res.error ?? "Swap failed");
          setResult({ success: false, message: res.error ?? "Swap failed" });
          return;
        }

        setResult(res.data ?? { success: true, message: "Swap successful!" });
      } else {
        const res = await executeBridge({
          source_chain: fromChain,
          amount,
          mode: bridgeSpeed,
        });

        if (!res.success) {
          setError(res.error ?? "Bridge failed");
          setResult({ success: false, message: res.error ?? "Bridge failed" });
          return;
        }

        setResult(res.data ?? { success: true, message: "Bridge successful!" });
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Execution failed";
      setError(msg);
      setResult({ success: false, message: msg });
    } finally {
      setExecuting(false);
    }
  }, [quote, mode, fromChain, fromToken, amount, bridgeSpeed]);

  const reset = useCallback(() => {
    setAmount("");
    setQuote(null);
    setQuoteError(null);
    setResult(null);
    setError(null);
  }, []);

  return {
    mode,
    setMode,
    fromChain,
    setFromChain,
    toChain,
    setToChain,
    fromToken,
    setFromToken,
    amount,
    setAmount,
    bridgeSpeed,
    setBridgeSpeed,
    bridgeChains,
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
