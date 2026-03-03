import React from "react";
import { View, Text, Pressable, Dimensions } from "react-native";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import { useRouter } from "expo-router";
import { Badge } from "@/components/ui/badge";
import { formatPercent, platformLabel } from "@/lib/utils";
import type { FeedMarket } from "@/api/client";

const CARD_WIDTH = Dimensions.get("window").width - 48;

interface FeaturedCardProps {
  market: FeedMarket;
}

export function FeaturedCard({ market }: FeaturedCardProps) {
  const router = useRouter();

  return (
    <Pressable
      onPress={() =>
        router.push(`/market/${market.platform}/${encodeURIComponent(market.id)}`)
      }
      className="rounded-2xl overflow-hidden"
      style={{ width: CARD_WIDTH }}
    >
      <View className="h-48 relative">
        {market.image ? (
          <Image
            source={{ uri: market.image }}
            className="absolute inset-0 w-full h-full"
            contentFit="cover"
          />
        ) : (
          <View className="absolute inset-0 bg-spredd-green/20" />
        )}
        <LinearGradient
          colors={["transparent", "rgba(15,15,26,0.9)"]}
          className="absolute inset-0"
        />

        <View className="absolute bottom-0 left-0 right-0 p-4 gap-2">
          <Badge variant="platform">{platformLabel(market.platform)}</Badge>
          <Text className="text-white font-semibold text-base" numberOfLines={2}>
            {market.title}
          </Text>
          <View className="flex-row gap-3">
            <Text className="text-spredd-green font-bold text-sm">
              Yes {formatPercent(market.yes_price)}
            </Text>
            <Text className="text-spredd-red font-bold text-sm">
              No {formatPercent(market.no_price)}
            </Text>
          </View>
        </View>
      </View>
    </Pressable>
  );
}
