import React, { useState } from "react";
import { View, Text } from "react-native";
import { BottomSheet } from "@/components/ui/bottom-sheet";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { GlassCard } from "@/components/ui/glass-card";

interface WithdrawSheetProps {
  open: boolean;
  onClose: () => void;
  balance?: string;
}

export function WithdrawSheet({
  open,
  onClose,
  balance = "0.00",
}: WithdrawSheetProps) {
  const [address, setAddress] = useState("");
  const [amount, setAmount] = useState("");

  return (
    <BottomSheet open={open} onClose={onClose} title="Withdraw">
      <View className="gap-5 pb-4">
        <GlassCard>
          <View className="flex-row justify-between items-center">
            <Text className="text-xs text-white/40">Available balance</Text>
            <Text className="text-lg font-bold text-white">${balance}</Text>
          </View>
        </GlassCard>

        <Input
          label="Destination address"
          value={address}
          onChangeText={setAddress}
          placeholder="Enter wallet address"
          autoCapitalize="none"
          autoCorrect={false}
        />

        <Input
          label="Amount (USDC)"
          value={amount}
          onChangeText={setAmount}
          placeholder="0.00"
          keyboardType="decimal-pad"
        />

        <Button
          variant="default"
          size="lg"
          onPress={onClose}
          disabled={!address || !amount}
        >
          Withdraw
        </Button>
      </View>
    </BottomSheet>
  );
}
