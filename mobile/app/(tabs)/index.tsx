import React from "react";
import {
  View,
  Text,
  ScrollView,
  FlatList,
  Pressable,
  RefreshControl,
  ActivityIndicator,
} from "react-native";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Search, Bell } from "lucide-react-native";
import { useHome } from "@/hooks/useHome";
import { CategoryPills } from "@/components/CategoryPills";
import { FeaturedCard } from "@/components/FeaturedCard";
import { LiveEventCard } from "@/components/LiveEventCard";
import { MarketGridCard } from "@/components/MarketGridCard";
import { Skeleton } from "@/components/ui/skeleton";

export default function HomePage() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const {
    categories,
    selectedCategory,
    setSelectedCategory,
    featured,
    live,
    markets,
    loading,
    refresh,
  } = useHome();

  const renderHeader = () => (
    <>
      {/* Header */}
      <View
        className="flex-row items-center justify-between px-5 pb-3"
        style={{ paddingTop: insets.top + 8 }}
      >
        <Text className="font-brand text-2xl text-spredd-green">SPREDD</Text>
        <View className="flex-row items-center gap-3">
          <Pressable
            onPress={() => router.push("/search")}
            className="w-10 h-10 items-center justify-center rounded-full bg-white/5"
          >
            <Search size={18} color="rgba(255,255,255,0.7)" />
          </Pressable>
          <Pressable className="w-10 h-10 items-center justify-center rounded-full bg-white/5">
            <Bell size={18} color="rgba(255,255,255,0.7)" />
          </Pressable>
        </View>
      </View>

      {/* Categories */}
      <CategoryPills
        categories={categories}
        selected={selectedCategory}
        onSelect={setSelectedCategory}
        className="mb-4"
      />

      {/* Featured */}
      {featured.length > 0 && (
        <View className="mb-5">
          <Text className="text-lg font-bold text-white px-5 mb-3">
            Featured
          </Text>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={{ paddingHorizontal: 20, gap: 12 }}
          >
            {featured.map((m) => (
              <FeaturedCard key={`${m.platform}-${m.id}`} market={m} />
            ))}
          </ScrollView>
        </View>
      )}

      {/* Live Events */}
      {live.length > 0 && (
        <View className="mb-5">
          <Text className="text-lg font-bold text-white px-5 mb-3">
            Live Events
          </Text>
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={{ paddingHorizontal: 20, gap: 12 }}
          >
            {live.map((m) => (
              <LiveEventCard key={`${m.platform}-${m.id}`} market={m} />
            ))}
          </ScrollView>
        </View>
      )}

      {/* Markets header */}
      <Text className="text-lg font-bold text-white px-5 mb-3">
        Markets
      </Text>
    </>
  );

  if (loading && markets.length === 0) {
    return (
      <View className="flex-1 bg-spredd-bg">
        <View style={{ paddingTop: insets.top + 8 }} className="px-5 gap-4">
          <Skeleton className="h-8 w-32" />
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-48 w-full rounded-2xl" />
          <Skeleton className="h-36 w-full rounded-2xl" />
          <Skeleton className="h-36 w-full rounded-2xl" />
        </View>
      </View>
    );
  }

  return (
    <View className="flex-1 bg-spredd-bg">
      <FlatList
        data={markets}
        keyExtractor={(item) => `${item.platform}-${item.id}`}
        renderItem={({ item }) => (
          <View className="px-5 mb-3">
            <MarketGridCard market={item} />
          </View>
        )}
        ListHeaderComponent={renderHeader}
        refreshControl={
          <RefreshControl
            refreshing={loading}
            onRefresh={refresh}
            tintColor="#00D973"
          />
        }
        contentContainerStyle={{ paddingBottom: 20 }}
      />
    </View>
  );
}
