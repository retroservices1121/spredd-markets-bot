import React from "react";
import { View, Text, Pressable, TextInput, ActivityIndicator } from "react-native";
import { BottomSheet } from "@/components/ui/bottom-sheet";
import { Button } from "@/components/ui/button";
import { GlassCard } from "@/components/ui/glass-card";
import { formatUSD } from "@/lib/utils";
import { cn } from "@/lib/utils";
import type { QuoteResponse } from "@/api/client";

interface TradeSheetProps {
  open: boolean;
  onClose: () => void;
  marketTitle: string;
  outcome: "yes" | "no" | null;
  onOutcomeChange: (o: "yes" | "no") => void;
  amount: string;
  onAmountChange: (a: string) => void;
  quote: QuoteResponse | null;
  quoteLoading: boolean;
  quoteError: string | null;
  executing: boolean;
  onExecute: () => void;
}

const QUICK_AMOUNTS = ["5", "10", "25", "50", "100"];

export function TradeSheet({
  open,
  onClose,
  marketTitle,
  outcome,
  onOutcomeChange,
  amount,
  onAmountChange,
  quote,
  quoteLoading,
  quoteError,
  executing,
  onExecute,
}: TradeSheetProps) {
  return (
    <BottomSheet open={open} onClose={onClose} title="Trade" snapPoints={["70%", "90%"]}>
      <View className="gap-5 pb-8">
        {/* Market title */}
        <Text className="text-sm text-white/60" numberOfLines={2}>
          {marketTitle}
        </Text>

        {/* Outcome selector */}
        <View className="flex-row gap-3">
          <Pressable
            onPress={() => onOutcomeChange("yes")}
            className={cn(
              "flex-1 py-3 rounded-xl items-center border",
              outcome === "yes"
                ? "bg-spredd-green border-spredd-green"
                : "bg-transparent border-white/15"
            )}
          >
            <Text
              className={cn(
                "font-bold text-base",
                outcome === "yes" ? "text-black" : "text-white/50"
              )}
            >
              Yes
            </Text>
          </Pressable>
          <Pressable
            onPress={() => onOutcomeChange("no")}
            className={cn(
              "flex-1 py-3 rounded-xl items-center border",
              outcome === "no"
                ? "bg-spredd-red border-spredd-red"
                : "bg-transparent border-white/15"
            )}
          >
            <Text
              className={cn(
                "font-bold text-base",
                outcome === "no" ? "text-white" : "text-white/50"
              )}
            >
              No
            </Text>
          </Pressable>
        </View>

        {/* Amount input */}
        <View className="gap-2">
          <Text className="text-sm font-medium text-white">Amount (USD)</Text>
          <View className="flex-row items-center bg-white/5 rounded-xl border border-white/10 px-4 h-14">
            <Text className="text-white/50 text-lg mr-1">$</Text>
            <TextInput
              value={amount}
              onChangeText={onAmountChange}
              keyboardType="decimal-pad"
              className="flex-1 text-white text-lg font-semibold"
              placeholderTextColor="rgba(255,255,255,0.3)"
              placeholder="0.00"
            />
          </View>
        </View>

        {/* Quick amounts */}
        <View className="flex-row gap-2">
          {QUICK_AMOUNTS.map((qa) => (
            <Pressable
              key={qa}
              onPress={() => onAmountChange(qa)}
              className={cn(
                "flex-1 py-2 rounded-lg items-center border",
                amount === qa
                  ? "bg-white/15 border-white/20"
                  : "bg-transparent border-white/8"
              )}
            >
              <Text className="text-xs font-medium text-white">${qa}</Text>
            </Pressable>
          ))}
        </View>

        {/* Quote details */}
        {quoteLoading && (
          <View className="py-4 items-center">
            <ActivityIndicator color="#00D973" />
          </View>
        )}

        {quoteError && (
          <Text className="text-xs text-spredd-red text-center">
            {quoteError}
          </Text>
        )}

        {quote && !quoteLoading && (
          <GlassCard className="gap-2">
            <View className="flex-row justify-between">
              <Text className="text-xs text-white/50">Price</Text>
              <Text className="text-xs text-white font-medium">
                {formatUSD(quote.price)}
              </Text>
            </View>
            <View className="flex-row justify-between">
              <Text className="text-xs text-white/50">Expected shares</Text>
              <Text className="text-xs text-white font-medium">
                {parseFloat(quote.expected_output).toFixed(2)}
              </Text>
            </View>
            {quote.price_impact != null && (
              <View className="flex-row justify-between">
                <Text className="text-xs text-white/50">Price impact</Text>
                <Text className="text-xs text-white font-medium">
                  {(quote.price_impact * 100).toFixed(2)}%
                </Text>
              </View>
            )}
          </GlassCard>
        )}

        {/* Execute button */}
        <Button
          variant={outcome === "no" ? "no" : "yes"}
          size="lg"
          onPress={onExecute}
          disabled={!outcome || !quote || executing}
          loading={executing}
        >
          {executing
            ? "Executing..."
            : outcome
              ? `Buy ${outcome === "yes" ? "Yes" : "No"} — ${formatUSD(amount)}`
              : "Select an outcome"}
        </Button>
      </View>
    </BottomSheet>
  );
}
