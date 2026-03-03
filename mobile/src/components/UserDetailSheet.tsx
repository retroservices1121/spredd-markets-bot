import React from "react";
import { View, Text } from "react-native";
import { BottomSheet } from "@/components/ui/bottom-sheet";
import { Avatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { GlassCard } from "@/components/ui/glass-card";
import { formatUSD } from "@/lib/utils";

interface UserDetailSheetProps {
  open: boolean;
  onClose: () => void;
  user: {
    username: string;
    avatar?: string;
    pnl?: number;
    win_rate?: number;
    total_trades?: number;
  } | null;
  isFollowing?: boolean;
  onFollow?: () => void;
}

export function UserDetailSheet({
  open,
  onClose,
  user,
  isFollowing,
  onFollow,
}: UserDetailSheetProps) {
  if (!user) return null;

  return (
    <BottomSheet open={open} onClose={onClose} snapPoints={["50%"]}>
      <View className="items-center gap-4 pb-4">
        <Avatar src={user.avatar} name={user.username} size="xl" />
        <Text className="text-xl font-bold text-white">{user.username}</Text>

        <View className="flex-row gap-4 w-full">
          <GlassCard className="flex-1 items-center">
            <Text className="text-xs text-white/40">P&L</Text>
            <Text className="text-sm font-bold text-spredd-green">
              {formatUSD(user.pnl ?? 0)}
            </Text>
          </GlassCard>
          <GlassCard className="flex-1 items-center">
            <Text className="text-xs text-white/40">Win Rate</Text>
            <Text className="text-sm font-bold text-white">
              {Math.round((user.win_rate ?? 0) * 100)}%
            </Text>
          </GlassCard>
          <GlassCard className="flex-1 items-center">
            <Text className="text-xs text-white/40">Trades</Text>
            <Text className="text-sm font-bold text-white">
              {user.total_trades ?? 0}
            </Text>
          </GlassCard>
        </View>

        <Button
          variant={isFollowing ? "outline" : "default"}
          size="default"
          onPress={onFollow}
          className="w-full"
        >
          {isFollowing ? "Following" : "Follow"}
        </Button>
      </View>
    </BottomSheet>
  );
}
