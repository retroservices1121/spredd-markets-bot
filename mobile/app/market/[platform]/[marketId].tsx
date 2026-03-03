import React from "react";
import { View, Pressable } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { ArrowLeft, Share2, MessageCircle } from "lucide-react-native";
import { MarketDetailView } from "@/components/MarketDetail";

export default function MarketDetailPage() {
  const { platform, marketId } = useLocalSearchParams<{
    platform: string;
    marketId: string;
  }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();

  if (!platform || !marketId) return null;

  return (
    <View className="flex-1 bg-spredd-bg">
      {/* Floating header */}
      <View
        className="absolute top-0 left-0 right-0 z-10 flex-row items-center justify-between px-4"
        style={{ paddingTop: insets.top + 4 }}
      >
        <Pressable
          onPress={() => router.back()}
          className="w-10 h-10 rounded-full bg-black/40 items-center justify-center"
        >
          <ArrowLeft size={20} color="#fff" />
        </Pressable>
        <View className="flex-row gap-2">
          <Pressable className="w-10 h-10 rounded-full bg-black/40 items-center justify-center">
            <MessageCircle size={18} color="#fff" />
          </Pressable>
          <Pressable className="w-10 h-10 rounded-full bg-black/40 items-center justify-center">
            <Share2 size={18} color="#fff" />
          </Pressable>
        </View>
      </View>

      <MarketDetailView
        platform={platform}
        marketId={decodeURIComponent(marketId)}
      />
    </View>
  );
}
