import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { motion } from "framer-motion";
import {
  ArrowRight,
  Zap,
  Clock,
  AlertCircle,
  CheckCircle2,
  Loader2,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useTelegram } from "@/contexts/TelegramContext";
import {
  getBridgeChains,
  getBridgeQuote,
  executeBridge,
  BridgeQuoteResponse,
} from "@/lib/api";
import { formatUSD } from "@/lib/utils";
import { toast } from "sonner";

export default function BridgePage() {
  const { initData, hapticFeedback } = useTelegram();
  const [selectedChain, setSelectedChain] = useState<string | null>(null);
  const [amount, setAmount] = useState("");
  const [bridgeMode, setBridgeMode] = useState<"fast" | "standard">("fast");
  const [quote, setQuote] = useState<BridgeQuoteResponse | null>(null);

  // Fetch available chains
  const { data: chainsData, isLoading: chainsLoading, refetch: refetchChains } = useQuery({
    queryKey: ["bridge-chains"],
    queryFn: () => getBridgeChains(initData),
  });

  // Get quote mutation
  const quoteMutation = useMutation({
    mutationFn: () =>
      getBridgeQuote(initData, {
        source_chain: selectedChain!,
        amount: amount,
      }),
    onSuccess: (data) => {
      setQuote(data);
    },
    onError: (error: Error) => {
      toast.error(error.message);
    },
  });

  // Execute bridge mutation
  const bridgeMutation = useMutation({
    mutationFn: () =>
      executeBridge(initData, {
        source_chain: selectedChain!,
        amount: amount,
        mode: bridgeMode,
      }),
    onSuccess: (data) => {
      hapticFeedback("success");
      toast.success(data.message);
      setQuote(null);
      setAmount("");
      setSelectedChain(null);
      refetchChains();
    },
    onError: (error: Error) => {
      hapticFeedback("error");
      toast.error(error.message);
    },
  });

  const chains = chainsData?.chains || [];
  const chainsWithBalance = chains.filter((c) => c.has_balance);

  const handleChainSelect = (chainId: string) => {
    hapticFeedback("light");
    setSelectedChain(chainId);
    setQuote(null);
  };

  const handleGetQuote = () => {
    if (!selectedChain || !amount || parseFloat(amount) <= 0) {
      toast.error("Please select a chain and enter an amount");
      return;
    }
    hapticFeedback("light");
    quoteMutation.mutate();
  };

  const handleBridge = () => {
    hapticFeedback("medium");
    bridgeMutation.mutate();
  };

  const handleMaxAmount = () => {
    const chain = chains.find((c) => c.id === selectedChain);
    if (chain) {
      setAmount(chain.balance);
      setQuote(null);
    }
  };

  return (
    <div className="p-4 space-y-4">
      {/* Header */}
      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}>
        <Card className="bg-gradient-to-br from-purple-500/20 to-blue-500/20 border-purple-500/30">
          <CardContent className="p-6">
            <h1 className="text-xl font-bold mb-2">Bridge USDC</h1>
            <p className="text-sm text-white/60">
              Bridge USDC from other chains to Polygon for trading on Polymarket
            </p>
          </CardContent>
        </Card>
      </motion.div>

      {/* Chain Selection */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
      >
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Select Source Chain</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {chainsLoading ? (
              <div className="space-y-2">
                <Skeleton className="h-16 w-full" />
                <Skeleton className="h-16 w-full" />
              </div>
            ) : chainsWithBalance.length > 0 ? (
              <div className="grid grid-cols-2 gap-2">
                {chainsWithBalance.map((chain) => (
                  <button
                    key={chain.id}
                    onClick={() => handleChainSelect(chain.id)}
                    className={`p-3 rounded-lg border text-left transition-all ${
                      selectedChain === chain.id
                        ? "border-spredd-orange bg-spredd-orange/10"
                        : "border-border hover:border-white/30"
                    }`}
                  >
                    <p className="font-medium capitalize">{chain.name}</p>
                    <p className="text-sm text-white/60">
                      {formatUSD(chain.balance)} USDC
                    </p>
                  </button>
                ))}
              </div>
            ) : (
              <div className="text-center py-6">
                <AlertCircle className="w-10 h-10 text-white/20 mx-auto mb-2" />
                <p className="text-white/60">No USDC found on other chains</p>
                <p className="text-xs text-white/40 mt-1">
                  Deposit USDC on Base, Arbitrum, or other supported chains
                </p>
              </div>
            )}
          </CardContent>
        </Card>
      </motion.div>

      {/* Amount Input */}
      {selectedChain && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Amount to Bridge</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex gap-2">
                <Input
                  type="number"
                  placeholder="0.00"
                  value={amount}
                  onChange={(e) => {
                    setAmount(e.target.value);
                    setQuote(null);
                  }}
                  className="flex-1"
                />
                <Button variant="outline" onClick={handleMaxAmount}>
                  MAX
                </Button>
              </div>

              <div className="flex items-center justify-between text-sm">
                <span className="text-white/60">Destination</span>
                <Badge variant="polymarket">Polygon</Badge>
              </div>

              <Button
                onClick={handleGetQuote}
                disabled={!amount || parseFloat(amount) <= 0 || quoteMutation.isPending}
                className="w-full"
              >
                {quoteMutation.isPending ? (
                  <>
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    Getting Quote...
                  </>
                ) : (
                  "Get Quote"
                )}
              </Button>
            </CardContent>
          </Card>
        </motion.div>
      )}

      {/* Quote Display */}
      {quote && (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Bridge Options</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              {/* Fast Bridge Option */}
              {quote.fast_bridge?.available && (
                <button
                  onClick={() => setBridgeMode("fast")}
                  className={`w-full p-4 rounded-lg border text-left transition-all ${
                    bridgeMode === "fast"
                      ? "border-spredd-orange bg-spredd-orange/10"
                      : "border-border hover:border-white/30"
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <Zap className="w-5 h-5 text-yellow-500" />
                      <span className="font-medium">Fast Bridge</span>
                    </div>
                    <Badge variant="outline" className="text-yellow-500 border-yellow-500/50">
                      ~30 sec
                    </Badge>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-sm">
                    <div>
                      <p className="text-white/60">You receive</p>
                      <p className="font-medium">
                        {formatUSD(quote.fast_bridge.output_amount)} USDC
                      </p>
                    </div>
                    <div>
                      <p className="text-white/60">Fee</p>
                      <p className="font-medium text-spredd-red">
                        {formatUSD(quote.fast_bridge.fee_amount)} ({quote.fast_bridge.fee_percent.toFixed(2)}%)
                      </p>
                    </div>
                  </div>
                </button>
              )}

              {/* Standard Bridge Option */}
              {quote.standard_bridge?.available && (
                <button
                  onClick={() => setBridgeMode("standard")}
                  className={`w-full p-4 rounded-lg border text-left transition-all ${
                    bridgeMode === "standard"
                      ? "border-spredd-orange bg-spredd-orange/10"
                      : "border-border hover:border-white/30"
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <Clock className="w-5 h-5 text-blue-500" />
                      <span className="font-medium">Standard Bridge</span>
                    </div>
                    <Badge variant="outline" className="text-blue-500 border-blue-500/50">
                      ~15 min
                    </Badge>
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-sm">
                    <div>
                      <p className="text-white/60">You receive</p>
                      <p className="font-medium">
                        {formatUSD(quote.standard_bridge.output_amount)} USDC
                      </p>
                    </div>
                    <div>
                      <p className="text-white/60">Fee</p>
                      <p className="font-medium text-spredd-green">FREE</p>
                    </div>
                  </div>
                </button>
              )}

              {/* Bridge Summary */}
              <div className="bg-spredd-dark rounded-lg p-3 space-y-2">
                <div className="flex items-center justify-center gap-2 text-sm">
                  <span className="capitalize">{selectedChain}</span>
                  <ArrowRight className="w-4 h-4" />
                  <span>Polygon</span>
                </div>
                <p className="text-center text-xs text-white/60">
                  {bridgeMode === "fast"
                    ? "Powered by Relay.link - instant liquidity"
                    : "Powered by Circle CCTP - official cross-chain protocol"}
                </p>
              </div>

              {/* Execute Button */}
              <Button
                onClick={handleBridge}
                disabled={bridgeMutation.isPending}
                className="w-full"
                size="lg"
              >
                {bridgeMutation.isPending ? (
                  <>
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    Bridging...
                  </>
                ) : (
                  <>
                    <CheckCircle2 className="w-4 h-4 mr-2" />
                    Bridge {formatUSD(amount)} USDC
                  </>
                )}
              </Button>
            </CardContent>
          </Card>
        </motion.div>
      )}

      {/* Info Card */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
      >
        <Card className="border-dashed">
          <CardContent className="p-4">
            <h3 className="font-medium mb-2">About Bridging</h3>
            <ul className="text-sm text-white/60 space-y-1">
              <li>- Fast Bridge: ~30 seconds, small fee (~0.1-0.5%)</li>
              <li>- Standard Bridge: ~15 minutes, free (gas only)</li>
              <li>- Both methods are secure and trustless</li>
              <li>- You need gas tokens on the source chain</li>
            </ul>
          </CardContent>
        </Card>
      </motion.div>
    </div>
  );
}
