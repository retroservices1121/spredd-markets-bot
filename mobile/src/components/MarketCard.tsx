import React from "react";
import { View, Text, Dimensions } from "react-native";
import { Image } from "expo-image";
import { LinearGradient } from "expo-linear-gradient";
import { Badge } from "@/components/ui/badge";
import { ProgressBar } from "@/components/ui/progress-bar";
import { FeedActionBar } from "./FeedActionBar";
import { CreatorInfo } from "./CreatorInfo";
import { formatVolume, timeUntil, platformLabel } from "@/lib/utils";
import type { FeedMarket } from "@/api/client";

const { height: SCREEN_HEIGHT } = Dimensions.get("window");

interface MarketCardProps {
  market: FeedMarket;
  onYes?: () => void;
  onNo?: () => void;
  isLiked?: boolean;
  isBookmarked?: boolean;
  onLike?: () => void;
  onBookmark?: () => void;
  onComment?: () => void;
  onShare?: () => void;
}

export function MarketCard({
  market,
  onYes,
  onNo,
  isLiked,
  isBookmarked,
  onLike,
  onBookmark,
  onComment,
  onShare,
}: MarketCardProps) {
  const yesPercent = Math.round((market.yes_price ?? 0.5) * 100);

  return (
    <View className="relative" style={{ height: SCREEN_HEIGHT }}>
      {/* Background image */}
      {market.image ? (
        <Image
          source={{ uri: market.image }}
          className="absolute inset-0 w-full h-full"
          contentFit="cover"
        />
      ) : (
        <View className="absolute inset-0 bg-spredd-bg" />
      )}

      {/* Gradient overlay */}
      <LinearGradient
        colors={[
          "transparent",
          "rgba(15,15,26,0.4)",
          "rgba(15,15,26,0.95)",
        ]}
        locations={[0, 0.4, 0.75]}
        className="absolute inset-0"
      />

      {/* Content */}
      <View className="absolute bottom-0 left-0 right-0 px-5 pb-28 gap-4">
        {/* Platform + time */}
        <View className="flex-row items-center gap-2">
          <Badge variant="platform">{platformLabel(market.platform)}</Badge>
          {market.end_date && (
            <Text className="text-xs text-white/50">
              {timeUntil(market.end_date)}
            </Text>
          )}
          {market.category && (
            <Badge variant="secondary">{market.category}</Badge>
          )}
        </View>

        {/* Title */}
        <Text className="text-2xl font-bold text-white leading-tight">
          {market.title}
        </Text>

        {/* Creator */}
        {market.creator && (
          <CreatorInfo
            username={market.creator.username}
            avatar={market.creator.avatar}
          />
        )}

        {/* Progress bar */}
        <ProgressBar yesPercent={yesPercent} />

        {/* Volume */}
        {market.volume != null && (
          <Text className="text-xs text-white/40">
            Volume: {formatVolume(market.volume)}
          </Text>
        )}

        {/* Yes / No buttons */}
        <View className="flex-row gap-3">
          <View className="flex-1">
            <View className="bg-spredd-green rounded-xl py-3 items-center active:opacity-80">
              <Text
                className="text-black font-bold text-base"
                onPress={onYes}
              >
                Yes {yesPercent}%
              </Text>
            </View>
          </View>
          <View className="flex-1">
            <View className="bg-spredd-red rounded-xl py-3 items-center active:opacity-80">
              <Text
                className="text-white font-bold text-base"
                onPress={onNo}
              >
                No {100 - yesPercent}%
              </Text>
            </View>
          </View>
        </View>
      </View>

      {/* Action bar (right side) */}
      <View className="absolute right-4 bottom-36">
        <FeedActionBar
          isLiked={isLiked}
          isBookmarked={isBookmarked}
          onLike={onLike}
          onBookmark={onBookmark}
          onComment={onComment}
          onShare={onShare}
        />
      </View>
    </View>
  );
}
