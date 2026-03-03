import React from "react";
import {
  View,
  Text,
  FlatList,
  Pressable,
  RefreshControl,
  ActivityIndicator,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useRanking } from "@/hooks/useRanking";
import { Avatar } from "@/components/ui/avatar";
import { Tabs } from "@/components/ui/tabs";
import { GlassCard } from "@/components/ui/glass-card";
import { formatUSD } from "@/lib/utils";
import { cn } from "@/lib/utils";
import type { LeaderboardEntry } from "@/api/client";

const PERIOD_TABS = [
  { id: "24h", label: "24H" },
  { id: "7d", label: "7D" },
  { id: "30d", label: "30D" },
  { id: "all", label: "All" },
];

export default function RankingPage() {
  const insets = useSafeAreaInsets();
  const { entries, loading, period, setPeriod } = useRanking();

  // Top 3 for podium
  const podium = entries.slice(0, 3);
  const rest = entries.slice(3);

  const renderPodium = () => {
    if (podium.length < 3) return null;
    // Order: 2nd, 1st, 3rd
    const ordered = [podium[1], podium[0], podium[2]];
    const heights = [100, 130, 80];
    const medals = ["\uD83E\uDD48", "\uD83E\uDD47", "\uD83E\uDD49"];

    return (
      <View className="flex-row justify-center items-end gap-3 mb-6 px-5">
        {ordered.map((entry, i) => (
          <View key={entry.user_id} className="items-center flex-1">
            <Avatar
              src={entry.avatar}
              name={entry.username}
              size={i === 1 ? "lg" : "md"}
            />
            <Text className="text-xs font-bold text-white mt-2">
              {entry.username}
            </Text>
            <Text className="text-[10px] text-spredd-green font-semibold">
              {formatUSD(entry.pnl)}
            </Text>
            <View
              className="w-full bg-spredd-green/10 rounded-t-xl mt-2 items-center justify-end pb-2"
              style={{ height: heights[i] }}
            >
              <Text className="text-2xl">{medals[i]}</Text>
              <Text className="text-xs font-bold text-white">
                #{entry.rank}
              </Text>
            </View>
          </View>
        ))}
      </View>
    );
  };

  const renderRow = ({ item }: { item: LeaderboardEntry }) => (
    <GlassCard className="flex-row items-center gap-3 mx-5 mb-2 py-3 px-4">
      <Text className="text-sm font-bold text-white/50 w-7 text-center">
        {item.rank}
      </Text>
      <Avatar src={item.avatar} name={item.username} size="sm" />
      <View className="flex-1">
        <Text className="text-sm font-semibold text-white">
          {item.username}
        </Text>
        <Text className="text-xs text-white/40">
          {item.total_trades} trades \u2022{" "}
          {Math.round(item.win_rate * 100)}% WR
        </Text>
      </View>
      <Text
        className={cn(
          "text-sm font-bold",
          item.pnl >= 0 ? "text-spredd-green" : "text-spredd-red"
        )}
      >
        {item.pnl >= 0 ? "+" : ""}
        {formatUSD(item.pnl)}
      </Text>
    </GlassCard>
  );

  const renderHeader = () => (
    <>
      <View
        className="px-5 pb-4"
        style={{ paddingTop: insets.top + 8 }}
      >
        <Text className="text-2xl font-bold text-white mb-4">
          Leaderboard
        </Text>
        <Tabs
          tabs={PERIOD_TABS}
          activeTab={period}
          onTabChange={(id) => setPeriod(id as any)}
        />
      </View>
      {renderPodium()}
    </>
  );

  if (loading && entries.length === 0) {
    return (
      <View className="flex-1 bg-spredd-bg items-center justify-center">
        <ActivityIndicator size="large" color="#00D973" />
      </View>
    );
  }

  return (
    <View className="flex-1 bg-spredd-bg">
      <FlatList
        data={rest}
        keyExtractor={(item) => item.user_id}
        renderItem={renderRow}
        ListHeaderComponent={renderHeader}
        contentContainerStyle={{ paddingBottom: 20 }}
      />
    </View>
  );
}
