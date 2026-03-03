import React from "react";
import { View, Pressable } from "react-native";
import { Heart, MessageCircle, Share2, Bookmark } from "lucide-react-native";

interface FeedActionBarProps {
  isLiked?: boolean;
  isBookmarked?: boolean;
  onLike?: () => void;
  onBookmark?: () => void;
  onComment?: () => void;
  onShare?: () => void;
}

export function FeedActionBar({
  isLiked,
  isBookmarked,
  onLike,
  onBookmark,
  onComment,
  onShare,
}: FeedActionBarProps) {
  return (
    <View className="items-center gap-5">
      <Pressable onPress={onLike} className="items-center">
        <Heart
          size={26}
          color={isLiked ? "#FF4059" : "rgba(255,255,255,0.7)"}
          fill={isLiked ? "#FF4059" : "transparent"}
        />
      </Pressable>

      <Pressable onPress={onComment} className="items-center">
        <MessageCircle size={26} color="rgba(255,255,255,0.7)" />
      </Pressable>

      <Pressable onPress={onBookmark} className="items-center">
        <Bookmark
          size={26}
          color={isBookmarked ? "#00D973" : "rgba(255,255,255,0.7)"}
          fill={isBookmarked ? "#00D973" : "transparent"}
        />
      </Pressable>

      <Pressable onPress={onShare} className="items-center">
        <Share2 size={26} color="rgba(255,255,255,0.7)" />
      </Pressable>
    </View>
  );
}
