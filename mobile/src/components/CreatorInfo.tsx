import React from "react";
import { View, Text } from "react-native";
import { Avatar } from "@/components/ui/avatar";

interface CreatorInfoProps {
  username: string;
  avatar?: string;
}

export function CreatorInfo({ username, avatar }: CreatorInfoProps) {
  return (
    <View className="flex-row items-center gap-2">
      <Avatar src={avatar} name={username} size="sm" />
      <Text className="text-sm text-white/70 font-medium">@{username}</Text>
    </View>
  );
}
