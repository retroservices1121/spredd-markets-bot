import React from "react";
import { View, Text, Pressable } from "react-native";
import Animated, {
  useAnimatedStyle,
  withTiming,
} from "react-native-reanimated";
import { cn } from "@/lib/utils";

interface ToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label?: string;
  description?: string;
  className?: string;
}

export function Toggle({
  checked,
  onChange,
  label,
  description,
  className,
}: ToggleProps) {
  const thumbStyle = useAnimatedStyle(() => ({
    transform: [
      { translateX: withTiming(checked ? 20 : 0, { duration: 200 }) },
    ],
  }));

  return (
    <Pressable
      onPress={() => onChange(!checked)}
      className={cn("flex-row items-center justify-between", className)}
    >
      {(label || description) && (
        <View className="flex-1 mr-3">
          {label && (
            <Text className="text-sm font-medium text-white">{label}</Text>
          )}
          {description && (
            <Text className="text-xs text-white/40 mt-0.5">
              {description}
            </Text>
          )}
        </View>
      )}
      <View
        className={cn(
          "w-11 h-6 rounded-full justify-center px-0.5",
          checked ? "bg-spredd-green" : "bg-white/15"
        )}
      >
        <Animated.View
          style={thumbStyle}
          className="w-5 h-5 rounded-full bg-white shadow"
        />
      </View>
    </Pressable>
  );
}
