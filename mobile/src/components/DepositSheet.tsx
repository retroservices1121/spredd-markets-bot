import React, { useState } from "react";
import { View, Text, Pressable } from "react-native";
import { BottomSheet } from "@/components/ui/bottom-sheet";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { GlassCard } from "@/components/ui/glass-card";
import { Copy } from "lucide-react-native";
import * as Haptics from "expo-haptics";

interface DepositSheetProps {
  open: boolean;
  onClose: () => void;
  walletAddress?: string;
}

export function DepositSheet({
  open,
  onClose,
  walletAddress = "0x...",
}: DepositSheetProps) {
  return (
    <BottomSheet open={open} onClose={onClose} title="Deposit">
      <View className="gap-5 pb-4">
        <Text className="text-sm text-white/60">
          Send USDC to your Spredd wallet address:
        </Text>

        <GlassCard className="gap-3">
          <Text className="text-xs text-white/40">Your wallet address</Text>
          <View className="flex-row items-center gap-2">
            <Text className="text-xs text-white font-mono flex-1" numberOfLines={1}>
              {walletAddress}
            </Text>
            <Pressable
              onPress={() => {
                Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
              }}
              className="p-1.5 bg-white/10 rounded-lg"
            >
              <Copy size={14} color="rgba(255,255,255,0.5)" />
            </Pressable>
          </View>
        </GlassCard>

        <View className="gap-1">
          <Text className="text-xs text-white/40">Supported tokens</Text>
          <Text className="text-sm text-white">USDC (Polygon, Solana)</Text>
        </View>

        <Button variant="default" size="lg" onPress={onClose}>
          Done
        </Button>
      </View>
    </BottomSheet>
  );
}
