import React from "react";
import { View, Text, Pressable } from "react-native";
import { Image } from "expo-image";
import { useRouter } from "expo-router";
import { ProgressBar } from "@/components/ui/progress-bar";
import { Badge } from "@/components/ui/badge";
import { formatVolume, timeUntil, platformLabel } from "@/lib/utils";
import type { FeedMarket } from "@/api/client";

interface MarketGridCardProps {
  market: FeedMarket;
}

export function MarketGridCard({ market }: MarketGridCardProps) {
  const router = useRouter();
  const yesPercent = Math.round((market.yes_price ?? 0.5) * 100);

  return (
    <Pressable
      onPress={() =>
        router.push(`/market/${market.platform}/${encodeURIComponent(market.id)}`)
      }
      className="bg-white/[0.06] rounded-2xl border border-white/8 overflow-hidden"
    >
      {market.image && (
        <Image
          source={{ uri: market.image }}
          className="w-full h-28"
          contentFit="cover"
        />
      )}
      <View className="p-3 gap-2">
        <View className="flex-row items-center gap-2">
          <Badge variant="platform">{platformLabel(market.platform)}</Badge>
          {market.end_date && (
            <Text className="text-xs text-white/40">
              {timeUntil(market.end_date)}
            </Text>
          )}
        </View>

        <Text className="text-sm font-medium text-white" numberOfLines={2}>
          {market.title}
        </Text>

        <ProgressBar yesPercent={yesPercent} />

        {market.volume != null && (
          <Text className="text-xs text-white/40">
            Vol: {formatVolume(market.volume)}
          </Text>
        )}
      </View>
    </Pressable>
  );
}
