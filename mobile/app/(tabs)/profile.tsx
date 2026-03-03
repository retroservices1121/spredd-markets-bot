import React, { useState } from "react";
import {
  View,
  Text,
  ScrollView,
  Pressable,
  RefreshControl,
  ActivityIndicator,
} from "react-native";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import {
  Settings,
  LogOut,
  TrendingUp,
  Trophy,
  Zap,
  Wallet,
  Copy,
} from "lucide-react-native";
import { useAuth } from "@/hooks/useAuth";
import { useProfileStats } from "@/hooks/useProfileStats";
import { Avatar } from "@/components/ui/avatar";
import { GlassCard } from "@/components/ui/glass-card";
import { Badge } from "@/components/ui/badge";
import { formatUSD, cn, platformLabel } from "@/lib/utils";
import type { Position } from "@/api/client";

export default function ProfilePage() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { user, logout } = useAuth();
  const { balances, positions, pnl, loading, refresh } = useProfileStats();
  const [refreshing, setRefreshing] = useState(false);

  const onRefresh = async () => {
    setRefreshing(true);
    refresh();
    setTimeout(() => setRefreshing(false), 1000);
  };

  if (loading && !pnl) {
    return (
      <View className="flex-1 bg-spredd-bg items-center justify-center">
        <ActivityIndicator size="large" color="#00D973" />
      </View>
    );
  }

  const stats = pnl ?? {
    total_pnl: 0,
    win_rate: 0,
    active_positions: 0,
    win_streak: 0,
    total_trades: 0,
    total_invested: 0,
  };

  const totalBalance = balances.reduce((sum, w) => {
    const wTotal = w.balances?.reduce(
      (s, b) => s + parseFloat(b.usd_value || b.balance || "0"),
      0
    );
    return sum + (wTotal || 0);
  }, 0);

  const renderPosition = (pos: Position) => (
    <GlassCard key={pos.id} className="mb-2">
      <Pressable
        onPress={() =>
          router.push(
            `/market/${pos.platform}/${encodeURIComponent(pos.market_id)}`
          )
        }
      >
        <View className="flex-row items-center justify-between mb-1">
          <Badge variant="platform">{platformLabel(pos.platform)}</Badge>
          <Badge
            variant={pos.outcome === "yes" ? "success" : "destructive"}
          >
            {pos.outcome.toUpperCase()}
          </Badge>
        </View>
        <Text className="text-sm font-medium text-white mb-2" numberOfLines={2}>
          {pos.market_title}
        </Text>
        <View className="flex-row justify-between">
          <View>
            <Text className="text-xs text-white/40">Entry</Text>
            <Text className="text-sm text-white">
              {Math.round(pos.entry_price * 100)}%
            </Text>
          </View>
          <View>
            <Text className="text-xs text-white/40">Current</Text>
            <Text className="text-sm text-white">
              {Math.round(pos.current_price * 100)}%
            </Text>
          </View>
          <View className="items-end">
            <Text className="text-xs text-white/40">PnL</Text>
            <Text
              className={cn(
                "text-sm font-bold",
                pos.pnl >= 0 ? "text-spredd-green" : "text-spredd-red"
              )}
            >
              {pos.pnl >= 0 ? "+" : ""}
              {formatUSD(pos.pnl)}
            </Text>
          </View>
        </View>
      </Pressable>
    </GlassCard>
  );

  return (
    <View className="flex-1 bg-spredd-bg">
      <ScrollView
        className="flex-1"
        contentContainerStyle={{ paddingBottom: 20 }}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={onRefresh}
            tintColor="#00D973"
          />
        }
      >
        {/* Header */}
        <View
          className="px-5 pb-6"
          style={{ paddingTop: insets.top + 8 }}
        >
          <View className="flex-row items-center justify-between mb-6">
            <Text className="text-2xl font-bold text-white">Profile</Text>
            <View className="flex-row gap-3">
              <Pressable onPress={() => router.push("/settings")}>
                <Settings size={22} color="rgba(255,255,255,0.6)" />
              </Pressable>
              <Pressable onPress={logout}>
                <LogOut size={22} color="rgba(255,255,255,0.6)" />
              </Pressable>
            </View>
          </View>

          {/* User card */}
          <View className="items-center mb-6">
            <Avatar
              name={user?.username || user?.first_name || "U"}
              src={user?.avatar}
              size="xl"
            />
            <Text className="text-lg font-bold text-white mt-3">
              {user?.username || user?.first_name || "Trader"}
            </Text>
            {user?.referral_code && (
              <Text className="text-xs text-white/40 mt-1">
                Referral: {user.referral_code}
              </Text>
            )}
          </View>
        </View>

        {/* Stats grid */}
        <View className="px-5 mb-4">
          <View className="flex-row gap-3 mb-3">
            <GlassCard className="flex-1 items-center">
              <TrendingUp size={18} color="#00D973" />
              <Text className="text-lg font-bold text-white mt-1">
                {formatUSD(stats.total_pnl)}
              </Text>
              <Text className="text-xs text-white/40">Total PnL</Text>
            </GlassCard>
            <GlassCard className="flex-1 items-center">
              <Trophy size={18} color="#00D973" />
              <Text className="text-lg font-bold text-white mt-1">
                {Math.round(stats.win_rate * 100)}%
              </Text>
              <Text className="text-xs text-white/40">Win Rate</Text>
            </GlassCard>
          </View>
          <View className="flex-row gap-3">
            <GlassCard className="flex-1 items-center">
              <Zap size={18} color="#00D973" />
              <Text className="text-lg font-bold text-white mt-1">
                {stats.win_streak}
              </Text>
              <Text className="text-xs text-white/40">Win Streak</Text>
            </GlassCard>
            <GlassCard className="flex-1 items-center">
              <Wallet size={18} color="#00D973" />
              <Text className="text-lg font-bold text-white mt-1">
                {formatUSD(totalBalance)}
              </Text>
              <Text className="text-xs text-white/40">Balance</Text>
            </GlassCard>
          </View>
        </View>

        {/* Wallets */}
        {balances.length > 0 && (
          <View className="px-5 mb-4">
            <Text className="text-sm font-semibold text-white mb-3">
              Wallets
            </Text>
            {balances.map((w, idx) => (
              <GlassCard key={idx} className="mb-2">
                <View
                  className="flex-row items-center gap-2 mb-2"
                >
                  <Text className="text-xs text-white/60 uppercase font-semibold">
                    {w.chain_family}
                  </Text>
                  <Text className="text-xs text-white/40 flex-1" numberOfLines={1}>
                    {w.public_key.slice(0, 8)}...{w.public_key.slice(-6)}
                  </Text>
                  <Copy size={12} color="rgba(255,255,255,0.3)" />
                </View>
                {w.balances?.map((b, bi) => (
                  <View key={bi} className="flex-row justify-between mt-1">
                    <Text className="text-sm text-white">{b.token}</Text>
                    <Text className="text-sm text-white/60">{b.balance}</Text>
                  </View>
                ))}
              </GlassCard>
            ))}
          </View>
        )}

        {/* Open Positions */}
        <View className="px-5">
          <View className="flex-row items-center justify-between mb-3">
            <Text className="text-sm font-semibold text-white">
              Open Positions ({positions.length})
            </Text>
          </View>
          {positions.length === 0 ? (
            <GlassCard className="items-center py-6">
              <Text className="text-white/40 text-sm">
                No open positions yet
              </Text>
              <Pressable onPress={() => router.push("/(tabs)")}>
                <Text className="text-spredd-green text-sm font-semibold mt-2">
                  Start Trading
                </Text>
              </Pressable>
            </GlassCard>
          ) : (
            positions.map(renderPosition)
          )}
        </View>
      </ScrollView>
    </View>
  );
}
