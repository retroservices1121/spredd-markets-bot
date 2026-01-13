import { useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { ArrowLeft, TrendingUp, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { useTelegram } from "@/contexts/TelegramContext";
import {
  getMarketDetails,
  getQuote,
  executeOrder,
  type QuoteResponse,
} from "@/lib/api";
import { formatPrice, formatUSD, getPlatformName } from "@/lib/utils";
import { toast } from "sonner";

export default function MarketDetailsPage() {
  const { platform, marketId } = useParams<{
    platform: string;
    marketId: string;
  }>();
  const navigate = useNavigate();
  const { initData, hapticFeedback } = useTelegram();

  const [outcome, setOutcome] = useState<"yes" | "no">("yes");
  const [side, setSide] = useState<"buy" | "sell">("buy");
  const [amount, setAmount] = useState("");
  const [quote, setQuote] = useState<QuoteResponse | null>(null);

  // Fetch market details
  const { data, isLoading, error } = useQuery({
    queryKey: ["market", platform, marketId],
    queryFn: () => getMarketDetails(initData, platform!, marketId!),
    enabled: !!platform && !!marketId,
  });

  // Get quote mutation
  const quoteMutation = useMutation({
    mutationFn: () =>
      getQuote(initData, {
        platform: platform!,
        market_id: marketId!,
        outcome,
        side,
        amount,
      }),
    onSuccess: (data) => {
      setQuote(data);
      hapticFeedback("light");
    },
    onError: (error: Error) => {
      toast.error(error.message);
      hapticFeedback("error");
    },
  });

  // Execute order mutation
  const orderMutation = useMutation({
    mutationFn: () =>
      executeOrder(initData, {
        platform: platform!,
        market_id: marketId!,
        outcome,
        side,
        amount,
        slippage_bps: 100,
      }),
    onSuccess: (data) => {
      toast.success(data.message);
      hapticFeedback("success");
      setAmount("");
      setQuote(null);
    },
    onError: (error: Error) => {
      toast.error(error.message);
      hapticFeedback("error");
    },
  });

  const handleGetQuote = () => {
    if (!amount || parseFloat(amount) <= 0) {
      toast.error("Enter a valid amount");
      return;
    }
    quoteMutation.mutate();
  };

  const handleExecute = () => {
    if (!quote) return;
    orderMutation.mutate();
  };

  const market = data?.market as any;

  if (isLoading) {
    return (
      <div className="p-4 space-y-4">
        <Skeleton className="h-8 w-32" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  if (error || !market) {
    return (
      <div className="p-4 text-center py-12">
        <AlertCircle className="w-12 h-12 text-spredd-red mx-auto mb-3" />
        <p className="text-white/60">Failed to load market</p>
        <Button variant="outline" className="mt-4" onClick={() => navigate(-1)}>
          Go Back
        </Button>
      </div>
    );
  }

  const platformVariant = platform as "kalshi" | "polymarket" | "opinion";

  return (
    <div className="p-4 space-y-4">
      {/* Back Button */}
      <button
        onClick={() => navigate(-1)}
        className="flex items-center gap-2 text-white/60 hover:text-white transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        <span className="text-sm">Back</span>
      </button>

      {/* Market Header */}
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-start justify-between gap-2">
            <CardTitle className="text-base leading-tight">
              {market.title || market.question}
            </CardTitle>
            <Badge variant={platformVariant}>
              {getPlatformName(platform!)}
            </Badge>
          </div>
        </CardHeader>
        <CardContent>
          {/* Current Prices */}
          <div className="grid grid-cols-2 gap-3 mb-4">
            <div className="bg-spredd-green/10 rounded-xl p-4 text-center">
              <div className="text-xs text-white/60 mb-1">Yes</div>
              <div className="text-2xl font-bold text-spredd-green">
                {formatPrice(market.yes_price)}
              </div>
            </div>
            <div className="bg-spredd-red/10 rounded-xl p-4 text-center">
              <div className="text-xs text-white/60 mb-1">No</div>
              <div className="text-2xl font-bold text-spredd-red">
                {formatPrice(market.no_price)}
              </div>
            </div>
          </div>

          {/* Stats */}
          <div className="flex items-center justify-center gap-4 text-sm text-white/40">
            <div className="flex items-center gap-1">
              <TrendingUp className="w-4 h-4" />
              <span>Vol: ${market.volume_24h || market.volume || "0"}</span>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Trading Card */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Trade</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Buy/Sell Tabs */}
          <Tabs value={side} onValueChange={(v) => setSide(v as "buy" | "sell")}>
            <TabsList className="w-full">
              <TabsTrigger value="buy" className="flex-1">
                Buy
              </TabsTrigger>
              <TabsTrigger value="sell" className="flex-1">
                Sell
              </TabsTrigger>
            </TabsList>
          </Tabs>

          {/* Outcome Selection */}
          <div className="grid grid-cols-2 gap-2">
            <Button
              variant={outcome === "yes" ? "success" : "outline"}
              onClick={() => setOutcome("yes")}
              className="h-12"
            >
              Yes
            </Button>
            <Button
              variant={outcome === "no" ? "destructive" : "outline"}
              onClick={() => setOutcome("no")}
              className="h-12"
            >
              No
            </Button>
          </div>

          {/* Amount Input */}
          <div>
            <label className="text-sm text-white/60 mb-2 block">
              {side === "buy" ? "Amount (USDC)" : "Shares to sell"}
            </label>
            <Input
              type="number"
              placeholder="0.00"
              value={amount}
              onChange={(e) => {
                setAmount(e.target.value);
                setQuote(null);
              }}
              className="text-lg h-12"
            />
          </div>

          {/* Quote Display */}
          {quote && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="bg-spredd-dark rounded-xl p-4 space-y-2"
            >
              <div className="flex justify-between text-sm">
                <span className="text-white/60">Expected Output</span>
                <span className="font-medium">
                  {side === "buy"
                    ? `${quote.expected_output} shares`
                    : formatUSD(quote.expected_output)}
                </span>
              </div>
              <div className="flex justify-between text-sm">
                <span className="text-white/60">Price</span>
                <span className="font-medium">{formatPrice(quote.price)}</span>
              </div>
              {quote.fees && Object.keys(quote.fees).length > 0 && (
                <div className="flex justify-between text-sm">
                  <span className="text-white/60">Fees</span>
                  <span className="font-medium">
                    {formatUSD(Object.values(quote.fees).reduce((a, b) => a + parseFloat(b), 0))}
                  </span>
                </div>
              )}
            </motion.div>
          )}

          {/* Action Buttons */}
          <div className="space-y-2">
            {!quote ? (
              <Button
                className="w-full h-12"
                onClick={handleGetQuote}
                disabled={!amount || quoteMutation.isPending}
              >
                {quoteMutation.isPending ? "Getting Quote..." : "Trade"}
              </Button>
            ) : (
              <Button
                className="w-full h-12"
                onClick={handleExecute}
                disabled={orderMutation.isPending}
              >
                {orderMutation.isPending
                  ? "Executing..."
                  : `${side === "buy" ? "Buy" : "Sell"} ${outcome.toUpperCase()}`}
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
