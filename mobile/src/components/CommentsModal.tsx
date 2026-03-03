import React, { useState, useEffect } from "react";
import { View, Text, FlatList, TextInput, Pressable, ActivityIndicator } from "react-native";
import { BottomSheet } from "@/components/ui/bottom-sheet";
import { Avatar } from "@/components/ui/avatar";
import { Send } from "lucide-react-native";
import { getComments, postComment, type Comment } from "@/api/client";

interface CommentsModalProps {
  open: boolean;
  onClose: () => void;
  marketId: string;
}

export function CommentsModal({ open, onClose, marketId }: CommentsModalProps) {
  const [comments, setComments] = useState<Comment[]>([]);
  const [loading, setLoading] = useState(true);
  const [text, setText] = useState("");
  const [posting, setPosting] = useState(false);

  useEffect(() => {
    if (open && marketId) {
      setLoading(true);
      getComments(marketId)
        .then((res) => setComments(res.comments))
        .finally(() => setLoading(false));
    }
  }, [open, marketId]);

  const handlePost = async () => {
    if (!text.trim() || posting) return;
    setPosting(true);
    try {
      const comment = await postComment(marketId, text.trim());
      setComments((prev) => [comment, ...prev]);
      setText("");
    } catch {}
    setPosting(false);
  };

  const renderComment = ({ item }: { item: Comment }) => (
    <View className="flex-row gap-3 py-3 border-b border-white/5">
      <Avatar src={item.avatar} name={item.username} size="sm" />
      <View className="flex-1">
        <Text className="text-xs font-semibold text-white">
          {item.username}
        </Text>
        <Text className="text-sm text-white/70 mt-0.5">{item.text}</Text>
      </View>
    </View>
  );

  return (
    <BottomSheet open={open} onClose={onClose} title="Comments" snapPoints={["60%", "85%"]}>
      <View className="flex-1">
        {loading ? (
          <View className="py-8 items-center">
            <ActivityIndicator color="#00D973" />
          </View>
        ) : (
          <FlatList
            data={comments}
            keyExtractor={(item) => item.id}
            renderItem={renderComment}
            ListEmptyComponent={
              <Text className="text-white/40 text-sm text-center py-8">
                No comments yet
              </Text>
            }
          />
        )}

        {/* Input */}
        <View className="flex-row items-center gap-2 pt-3 border-t border-white/10">
          <TextInput
            value={text}
            onChangeText={setText}
            placeholder="Add a comment..."
            placeholderTextColor="rgba(255,255,255,0.3)"
            className="flex-1 bg-white/5 rounded-full px-4 py-2.5 text-sm text-white"
          />
          <Pressable
            onPress={handlePost}
            disabled={!text.trim() || posting}
            className="p-2"
          >
            <Send
              size={20}
              color={text.trim() ? "#00D973" : "rgba(255,255,255,0.3)"}
            />
          </Pressable>
        </View>
      </View>
    </BottomSheet>
  );
}
