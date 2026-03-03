import React, { useCallback, useState } from "react";
import {
  View,
  Text,
  FlatList,
  Dimensions,
  ActivityIndicator,
  ViewToken,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { useRouter } from "expo-router";
import { useFeed } from "@/hooks/useFeed";
import { useLikes } from "@/hooks/useLikes";
import { useBookmarks } from "@/hooks/useBookmarks";
import { MarketCard } from "@/components/MarketCard";
import { CommentsModal } from "@/components/CommentsModal";
import { ShareModal } from "@/components/ShareModal";
import type { FeedMarket } from "@/api/client";

const { height: SCREEN_HEIGHT } = Dimensions.get("window");

export default function FeedPage() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { markets, loading, hasMore, loadMore, refresh } = useFeed();
  const likes = useLikes();
  const bookmarks = useBookmarks();

  const [commentsMarketId, setCommentsMarketId] = useState<string | null>(null);
  const [shareMarket, setShareMarket] = useState<FeedMarket | null>(null);

  const onViewableItemsChanged = useCallback(
    ({ viewableItems }: { viewableItems: ViewToken[] }) => {
      // Could track current visible market for analytics
    },
    []
  );

  const renderItem = useCallback(
    ({ item }: { item: FeedMarket }) => (
      <MarketCard
        market={item}
        onYes={() =>
          router.push(
            `/market/${item.platform}/${encodeURIComponent(item.id)}`
          )
        }
        onNo={() =>
          router.push(
            `/market/${item.platform}/${encodeURIComponent(item.id)}`
          )
        }
        isLiked={likes.isLiked(item.platform, item.id)}
        isBookmarked={bookmarks.isBookmarked(item.platform, item.id)}
        onLike={() => likes.toggle(item.platform, item.id)}
        onBookmark={() => bookmarks.toggle(item.platform, item.id)}
        onComment={() => setCommentsMarketId(item.id)}
        onShare={() => setShareMarket(item)}
      />
    ),
    [likes, bookmarks, router]
  );

  if (loading && markets.length === 0) {
    return (
      <View className="flex-1 bg-spredd-bg items-center justify-center">
        <ActivityIndicator size="large" color="#00D973" />
      </View>
    );
  }

  return (
    <View className="flex-1 bg-spredd-bg">
      <FlatList
        data={markets}
        keyExtractor={(item) => `${item.platform}-${item.id}`}
        renderItem={renderItem}
        pagingEnabled
        snapToInterval={SCREEN_HEIGHT}
        snapToAlignment="start"
        decelerationRate="fast"
        showsVerticalScrollIndicator={false}
        onEndReached={() => {
          if (hasMore) loadMore();
        }}
        onEndReachedThreshold={0.5}
        onViewableItemsChanged={onViewableItemsChanged}
        viewabilityConfig={{ itemVisiblePercentThreshold: 50 }}
        getItemLayout={(_, index) => ({
          length: SCREEN_HEIGHT,
          offset: SCREEN_HEIGHT * index,
          index,
        })}
      />

      {commentsMarketId && (
        <CommentsModal
          open={!!commentsMarketId}
          onClose={() => setCommentsMarketId(null)}
          marketId={commentsMarketId}
        />
      )}

      {shareMarket && (
        <ShareModal
          open={!!shareMarket}
          onClose={() => setShareMarket(null)}
          title={shareMarket.title}
          platform={shareMarket.platform}
          marketId={shareMarket.id}
        />
      )}
    </View>
  );
}
