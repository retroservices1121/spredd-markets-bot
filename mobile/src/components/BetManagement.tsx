import React, { useState } from "react";
import { View, Text } from "react-native";
import { BottomSheet } from "@/components/ui/bottom-sheet";
import { Button } from "@/components/ui/button";
import { GlassCard } from "@/components/ui/glass-card";
import { formatUSD, formatPercent } from "@/lib/utils";
import { cn } from "@/lib/utils";
import type { Position } from "@/api/client";

interface BetManagementProps {
  position: Position;
  open: boolean;
  onClose: () => void;
  onSell: (amount: number) => void;
}

export function BetManagement({
  position,
  open,
  onClose,
  onSell,
}: BetManagementProps) {
  const [sellPercent, setSellPercent] = useState(100);
  const sellAmount = (position.token_amount * sellPercent) / 100;
  const estimatedReturn = sellAmount * position.current_price;
  const isProfit = position.pnl >= 0;

  return (
    <BottomSheet open={open} onClose={onClose} title="Manage Position">
      <View className="gap-5 pb-4">
        {/* Position summary */}
        <GlassCard className="gap-2">
          <Text className="text-sm font-medium text-white">
            {position.market_title}
          </Text>
          <View className="flex-row justify-between">
            <Text className="text-xs text-white/50">Outcome</Text>
            <Text
              className={cn(
                "text-xs font-semibold uppercase",
                position.outcome.toLowerCase() === "yes"
                  ? "text-spredd-green"
                  : "text-spredd-red"
              )}
            >
              {position.outcome}
            </Text>
          </View>
          <View className="flex-row justify-between">
            <Text className="text-xs text-white/50">Entry price</Text>
            <Text className="text-xs text-white font-medium">
              {formatPercent(position.entry_price)}
            </Text>
          </View>
          <View className="flex-row justify-between">
            <Text className="text-xs text-white/50">Current price</Text>
            <Text className="text-xs text-white font-medium">
              {formatPercent(position.current_price)}
            </Text>
          </View>
          <View className="flex-row justify-between">
            <Text className="text-xs text-white/50">P&L</Text>
            <Text
              className={cn(
                "text-xs font-bold",
                isProfit ? "text-spredd-green" : "text-spredd-red"
              )}
            >
              {isProfit ? "+" : ""}
              {formatUSD(position.pnl)}
            </Text>
          </View>
        </GlassCard>

        {/* Sell percentage buttons */}
        <View className="gap-2">
          <Text className="text-sm font-medium text-white">Sell amount</Text>
          <View className="flex-row gap-2">
            {[25, 50, 75, 100].map((pct) => (
              <Button
                key={pct}
                variant={sellPercent === pct ? "default" : "outline"}
                size="sm"
                onPress={() => setSellPercent(pct)}
                className="flex-1"
              >
                {pct}%
              </Button>
            ))}
          </View>
        </View>

        {/* Estimate */}
        <GlassCard className="gap-1">
          <View className="flex-row justify-between">
            <Text className="text-xs text-white/50">Selling</Text>
            <Text className="text-xs text-white font-medium">
              {sellAmount.toFixed(2)} shares
            </Text>
          </View>
          <View className="flex-row justify-between">
            <Text className="text-xs text-white/50">Est. return</Text>
            <Text className="text-xs text-spredd-green font-medium">
              {formatUSD(estimatedReturn)}
            </Text>
          </View>
        </GlassCard>

        <Button
          variant="destructive"
          size="lg"
          onPress={() => onSell(sellAmount)}
        >
          Sell {sellPercent}% — {formatUSD(estimatedReturn)}
        </Button>
      </View>
    </BottomSheet>
  );
}
