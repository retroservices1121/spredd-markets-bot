import React, { useEffect } from "react";
import { View, Text } from "react-native";
import * as Haptics from "expo-haptics";
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withSpring,
} from "react-native-reanimated";
import { Modal } from "@/components/ui/modal";
import { Button } from "@/components/ui/button";
import { CheckCircle2, XCircle } from "lucide-react-native";
import type { TradeResponse } from "@/api/client";

interface TradeConfirmProps {
  open: boolean;
  onClose: () => void;
  result: TradeResponse | null;
}

export function TradeConfirm({ open, onClose, result }: TradeConfirmProps) {
  const scale = useSharedValue(0.5);

  useEffect(() => {
    if (open && result) {
      scale.value = withSpring(1, { damping: 12, stiffness: 200 });
      if (result.success) {
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
      } else {
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);
      }
    } else {
      scale.value = 0.5;
    }
  }, [open, result, scale]);

  const iconStyle = useAnimatedStyle(() => ({
    transform: [{ scale: scale.value }],
  }));

  if (!result) return null;

  return (
    <Modal open={open} onClose={onClose}>
      <View className="items-center gap-4 py-4">
        <Animated.View style={iconStyle}>
          {result.success ? (
            <CheckCircle2 size={64} color="#00D973" />
          ) : (
            <XCircle size={64} color="#FF4059" />
          )}
        </Animated.View>

        <Text className="text-xl font-bold text-white">
          {result.success ? "Trade Executed!" : "Trade Failed"}
        </Text>

        <Text className="text-sm text-white/50 text-center">
          {result.success
            ? result.message || "Your trade was placed successfully."
            : result.error || "Something went wrong. Please try again."}
        </Text>

        {result.tx_hash && (
          <Text className="text-xs text-white/30 font-mono">
            TX: {result.tx_hash.slice(0, 10)}...{result.tx_hash.slice(-8)}
          </Text>
        )}

        <Button
          variant={result.success ? "default" : "outline"}
          size="lg"
          onPress={onClose}
          className="w-full mt-2"
        >
          {result.success ? "Done" : "Close"}
        </Button>
      </View>
    </Modal>
  );
}
