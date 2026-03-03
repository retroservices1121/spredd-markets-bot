import React from "react";
import {
  View,
  Text,
  TextInput,
  FlatList,
  Pressable,
  ActivityIndicator,
} from "react-native";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { ArrowLeft, X, Clock, Trash2 } from "lucide-react-native";
import { useSearch } from "@/hooks/useSearch";
import { MarketGridCard } from "@/components/MarketGridCard";
import type { FeedMarket } from "@/api/client";

export default function SearchPage() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const {
    query,
    setQuery,
    results,
    loading,
    recentSearches,
    addRecentSearch,
    clearRecent,
  } = useSearch();

  const handleSubmit = () => {
    if (query.trim()) addRecentSearch(query.trim());
  };

  const handleRecent = (q: string) => {
    setQuery(q);
    addRecentSearch(q);
  };

  const renderResult = ({ item, index }: { item: FeedMarket; index: number }) => (
    <View className={index % 2 === 0 ? "flex-1 pr-1.5" : "flex-1 pl-1.5"}>
      <MarketGridCard market={item} />
    </View>
  );

  const renderEmpty = () => {
    if (loading) {
      return (
        <View className="items-center py-12">
          <ActivityIndicator size="large" color="#00D973" />
        </View>
      );
    }

    if (query.trim() && results.length === 0) {
      return (
        <View className="items-center py-12">
          <Text className="text-white/40 text-sm">
            No markets found for "{query}"
          </Text>
        </View>
      );
    }

    // Show recent searches when no query
    if (!query.trim() && recentSearches.length > 0) {
      return (
        <View className="px-5">
          <View className="flex-row items-center justify-between mb-3">
            <Text className="text-sm font-semibold text-white">
              Recent Searches
            </Text>
            <Pressable onPress={clearRecent}>
              <Trash2 size={16} color="rgba(255,255,255,0.4)" />
            </Pressable>
          </View>
          {recentSearches.map((q) => (
            <Pressable
              key={q}
              onPress={() => handleRecent(q)}
              className="flex-row items-center gap-3 py-3 border-b border-white/5"
            >
              <Clock size={16} color="rgba(255,255,255,0.3)" />
              <Text className="text-sm text-white/70 flex-1">{q}</Text>
            </Pressable>
          ))}
        </View>
      );
    }

    return (
      <View className="items-center py-12">
        <Text className="text-white/30 text-sm">
          Search for prediction markets
        </Text>
      </View>
    );
  };

  // Pair up results for 2-column grid
  const pairedData: FeedMarket[][] = [];
  for (let i = 0; i < results.length; i += 2) {
    pairedData.push(results.slice(i, i + 2));
  }

  return (
    <View className="flex-1 bg-spredd-bg">
      {/* Search header */}
      <View
        className="px-4 pb-3 border-b border-white/8"
        style={{ paddingTop: insets.top + 8 }}
      >
        <View className="flex-row items-center gap-3">
          <Pressable onPress={() => router.back()}>
            <ArrowLeft size={22} color="#fff" />
          </Pressable>
          <View className="flex-1 flex-row items-center bg-white/[0.08] rounded-xl px-4 h-11">
            <TextInput
              value={query}
              onChangeText={setQuery}
              onSubmitEditing={handleSubmit}
              placeholder="Search markets..."
              placeholderTextColor="rgba(255,255,255,0.3)"
              className="flex-1 text-white text-sm"
              autoFocus
              returnKeyType="search"
            />
            {query.length > 0 && (
              <Pressable onPress={() => setQuery("")}>
                <X size={18} color="rgba(255,255,255,0.4)" />
              </Pressable>
            )}
          </View>
        </View>
      </View>

      {/* Results */}
      {results.length > 0 ? (
        <FlatList
          data={pairedData}
          keyExtractor={(_, i) => String(i)}
          renderItem={({ item: pair }) => (
            <View className="flex-row px-5 mb-3">
              {pair.map((market, i) => (
                <View
                  key={market.id}
                  className={i === 0 ? "flex-1 pr-1.5" : "flex-1 pl-1.5"}
                >
                  <MarketGridCard market={market} />
                </View>
              ))}
              {pair.length === 1 && <View className="flex-1 pl-1.5" />}
            </View>
          )}
          contentContainerStyle={{ paddingTop: 16, paddingBottom: 20 }}
          ListFooterComponent={
            loading ? (
              <ActivityIndicator
                size="small"
                color="#00D973"
                style={{ marginTop: 12 }}
              />
            ) : null
          }
        />
      ) : (
        <View className="flex-1 pt-4">{renderEmpty()}</View>
      )}
    </View>
  );
}
