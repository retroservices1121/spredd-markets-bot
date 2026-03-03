import React, { useState, useEffect } from "react";
import { View, Text, ScrollView, ActivityIndicator } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { GlassCard } from "@/components/ui/glass-card";
import { ProgressBar } from "@/components/ui/progress-bar";
import { PriceChart } from "./PriceChart";
import { CreatorInfo } from "./CreatorInfo";
import { TradeSheet } from "./TradeSheet";
import { TradeConfirm } from "./TradeConfirm";
import { CommentsModal } from "./CommentsModal";
import { ShareModal } from "./ShareModal";
import { useTrade } from "@/hooks/useTrade";
import {
  getMarketDetail,
  type FeedMarket,
} from "@/api/client";
import {
  formatVolume,
  formatPercent,
  timeUntil,
  platformLabel,
} from "@/lib/utils";

interface MarketDetailProps {
  platform: string;
  marketId: string;
}

export function MarketDetailView({ platform, marketId }: MarketDetailProps) {
  const insets = useSafeAreaInsets();
  const [market, setMarket] = useState<Record<string, any> | null>(null);
  const [loading, setLoading] = useState(true);
  const [tradeOpen, setTradeOpen] = useState(false);
  const [commentsOpen, setCommentsOpen] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const trade = useTrade(marketId, platform);

  useEffect(() => {
    getMarketDetail(platform, marketId)
      .then(setMarket)
      .finally(() => setLoading(false));
  }, [platform, marketId]);

  if (loading) {
    return (
      <View className="flex-1 bg-spredd-bg items-center justify-center">
        <ActivityIndicator size="large" color="#00D973" />
      </View>
    );
  }

  if (!market) {
    return (
      <View className="flex-1 bg-spredd-bg items-center justify-center">
        <Text className="text-white/50">Market not found</Text>
      </View>
    );
  }

  const title = String(market.title || market.question || "");
  const yesPrice = Number(market.yes_price ?? 0.5);
  const noPrice = Number(market.no_price ?? 0.5);
  const yesPercent = Math.round(yesPrice * 100);
  const volume = market.volume;
  const endDate = market.end_date as string | undefined;
  const image = market.image as string | undefined;
  const description = market.description as string | undefined;

  const handleTrade = (outcome: "yes" | "no") => {
    trade.setOutcome(outcome);
    setTradeOpen(true);
  };

  const handleExecute = async () => {
    await trade.handleExecute();
    setTradeOpen(false);
    setConfirmOpen(true);
  };

  return (
    <View className="flex-1 bg-spredd-bg">
      <ScrollView className="flex-1" contentContainerStyle={{ paddingBottom: 120 }}>
        {/* Hero image */}
        {image && (
          <View className="h-56 relative">
            <Image
              source={{ uri: image }}
              className="w-full h-full"
              contentFit="cover"
            />
            <LinearGradient
              colors={["transparent", "#0F0F1A"]}
              className="absolute inset-0"
            />
          </View>
        )}

        <View className="px-5 gap-4" style={{ marginTop: image ? -20 : insets.top + 16 }}>
          {/* Tags */}
          <View className="flex-row items-center gap-2">
            <Badge variant="platform">{platformLabel(platform)}</Badge>
            {endDate && (
              <Text className="text-xs text-white/40">
                {timeUntil(endDate)}
              </Text>
            )}
          </View>

          {/* Title */}
          <Text className="text-xl font-bold text-white">{title}</Text>

          {/* Creator */}
          {market.creator && (
            <CreatorInfo
              username={String((market.creator as any).username)}
              avatar={(market.creator as any).avatar}
            />
          )}

          {/* Progress */}
          <ProgressBar yesPercent={yesPercent} />

          {/* Volume / Stats */}
          <View className="flex-row gap-4">
            {volume != null && (
              <GlassCard className="flex-1">
                <Text className="text-xs text-white/40">Volume</Text>
                <Text className="text-sm font-bold text-white">
                  {formatVolume(volume)}
                </Text>
              </GlassCard>
            )}
            <GlassCard className="flex-1">
              <Text className="text-xs text-white/40">Yes Price</Text>
              <Text className="text-sm font-bold text-spredd-green">
                {formatPercent(yesPrice)}
              </Text>
            </GlassCard>
            <GlassCard className="flex-1">
              <Text className="text-xs text-white/40">No Price</Text>
              <Text className="text-sm font-bold text-spredd-red">
                {formatPercent(noPrice)}
              </Text>
            </GlassCard>
          </View>

          {/* Chart */}
          <GlassCard>
            <PriceChart data={market.chart_data as any} />
          </GlassCard>

          {/* Description */}
          {description && (
            <View className="gap-2">
              <Text className="text-sm font-semibold text-white">
                About this market
              </Text>
              <Text className="text-sm text-white/60 leading-5">
                {description}
              </Text>
            </View>
          )}
        </View>
      </ScrollView>

      {/* Bottom trade buttons */}
      <View
        className="absolute bottom-0 left-0 right-0 flex-row gap-3 px-5 pt-3 bg-spredd-bg border-t border-white/8"
        style={{ paddingBottom: insets.bottom + 12 }}
      >
        <Button
          variant="yes"
          size="lg"
          onPress={() => handleTrade("yes")}
          className="flex-1"
        >
          Yes {formatPercent(yesPrice)}
        </Button>
        <Button
          variant="no"
          size="lg"
          onPress={() => handleTrade("no")}
          className="flex-1"
        >
          No {formatPercent(noPrice)}
        </Button>
      </View>

      {/* Sheets */}
      <TradeSheet
        open={tradeOpen}
        onClose={() => setTradeOpen(false)}
        marketTitle={title}
        outcome={trade.outcome}
        onOutcomeChange={trade.setOutcome}
        amount={trade.amount}
        onAmountChange={trade.setAmount}
        quote={trade.quote}
        quoteLoading={trade.quoteLoading}
        quoteError={trade.quoteError}
        executing={trade.executing}
        onExecute={handleExecute}
      />

      <TradeConfirm
        open={confirmOpen}
        onClose={() => {
          setConfirmOpen(false);
          trade.reset();
        }}
        result={trade.result}
      />

      <CommentsModal
        open={commentsOpen}
        onClose={() => setCommentsOpen(false)}
        marketId={marketId}
      />

      <ShareModal
        open={shareOpen}
        onClose={() => setShareOpen(false)}
        title={title}
        platform={platform}
        marketId={marketId}
      />
    </View>
  );
}
