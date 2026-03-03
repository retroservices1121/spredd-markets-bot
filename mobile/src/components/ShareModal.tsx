import React from "react";
import { View, Text, Pressable, Share } from "react-native";
import { Modal } from "@/components/ui/modal";
import { Copy, Share2 } from "lucide-react-native";
import * as Haptics from "expo-haptics";

interface ShareModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  platform: string;
  marketId: string;
}

export function ShareModal({
  open,
  onClose,
  title,
  platform,
  marketId,
}: ShareModalProps) {
  const shareUrl = `https://spredd.app/market/${platform}/${marketId}`;

  const handleShare = async () => {
    try {
      await Share.share({
        message: `${title}\n\n${shareUrl}`,
      });
    } catch {}
  };

  const handleCopy = async () => {
    // Clipboard is available via expo-clipboard if needed
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    onClose();
  };

  return (
    <Modal open={open} onClose={onClose} title="Share">
      <View className="gap-3">
        <Text className="text-sm text-white/60" numberOfLines={2}>
          {title}
        </Text>

        <Pressable
          onPress={handleShare}
          className="flex-row items-center gap-3 py-3 border-b border-white/8"
        >
          <Share2 size={20} color="#00D973" />
          <Text className="text-sm text-white font-medium">
            Share via...
          </Text>
        </Pressable>

        <Pressable
          onPress={handleCopy}
          className="flex-row items-center gap-3 py-3"
        >
          <Copy size={20} color="rgba(255,255,255,0.5)" />
          <Text className="text-sm text-white font-medium">Copy link</Text>
        </Pressable>
      </View>
    </Modal>
  );
}
