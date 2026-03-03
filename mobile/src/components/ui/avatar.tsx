import React from "react";
import { View, Text } from "react-native";
import { Image } from "expo-image";
import { cn } from "@/lib/utils";

interface AvatarProps {
  src?: string;
  name?: string;
  size?: "sm" | "md" | "lg" | "xl";
  online?: boolean;
  className?: string;
}

const sizeMap = {
  sm: "w-8 h-8",
  md: "w-10 h-10",
  lg: "w-14 h-14",
  xl: "w-20 h-20",
};

const textSizeMap = {
  sm: "text-xs",
  md: "text-sm",
  lg: "text-xl",
  xl: "text-2xl",
};

const ringSizeMap = {
  sm: "w-2.5 h-2.5",
  md: "w-3 h-3",
  lg: "w-3.5 h-3.5",
  xl: "w-4 h-4",
};

export function Avatar({
  src,
  name,
  size = "md",
  online,
  className,
}: AvatarProps) {
  const initials = (name || "U")
    .split(" ")
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

  return (
    <View className={cn("relative shrink-0", className)}>
      {src ? (
        <Image
          source={{ uri: src }}
          className={cn("rounded-full bg-white/10", sizeMap[size])}
          contentFit="cover"
        />
      ) : (
        <View
          className={cn(
            "rounded-full bg-spredd-green/20 items-center justify-center",
            sizeMap[size]
          )}
        >
          <Text
            className={cn(
              "font-bold text-spredd-green",
              textSizeMap[size]
            )}
          >
            {initials}
          </Text>
        </View>
      )}
      {online !== undefined && (
        <View
          className={cn(
            "absolute bottom-0 right-0 rounded-full border-2 border-spredd-bg",
            ringSizeMap[size],
            online ? "bg-spredd-green" : "bg-white/30"
          )}
        />
      )}
    </View>
  );
}
