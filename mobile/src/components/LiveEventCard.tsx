import React from "react";
import { View, Text, Pressable } from "react-native";
import { Image } from "expo-image";
import { useRouter } from "expo-router";
import { Badge } from "@/components/ui/badge";
import { formatPercent, timeUntil, platformLabel } from "@/lib/utils";
import type { FeedMarket } from "@/api/client";

interface LiveEventCardProps {
  market: FeedMarket;
}

export function LiveEventCard({ market }: LiveEventCardProps) {
  const router = useRouter();

  return (
    <Pressable
      onPress={() =>
        router.push(`/market/${market.platform}/${encodeURIComponent(market.id)}`)
      }
      className="w-40 bg-white/[0.06] rounded-2xl border border-white/8 overflow-hidden"
    >
      {market.image && (
        <Image
          source={{ uri: market.image }}
          className="w-full h-20"
          contentFit="cover"
        />
      )}
      <View className="p-3 gap-1.5">
        <View className="flex-row items-center gap-1">
          <View className="w-1.5 h-1.5 rounded-full bg-spredd-red" />
          <Text className="text-[10px] text-spredd-red font-medium">LIVE</Text>
          {market.end_date && (
            <Text className="text-[10px] text-white/40 ml-1">
              {timeUntil(market.end_date)}
            </Text>
          )}
        </View>
        <Text className="text-xs font-medium text-white" numberOfLines={2}>
          {market.title}
        </Text>
        <Text className="text-xs text-spredd-green font-semibold">
          Yes {formatPercent(market.yes_price)}
        </Text>
      </View>
    </Pressable>
  );
}
