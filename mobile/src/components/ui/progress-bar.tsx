import React from "react";
import { View, Text } from "react-native";
import { cn } from "@/lib/utils";

interface ProgressBarProps {
  yesPercent: number;
  showLabels?: boolean;
  className?: string;
}

export function ProgressBar({
  yesPercent,
  showLabels = true,
  className,
}: ProgressBarProps) {
  const noPercent = 100 - yesPercent;

  return (
    <View className={cn("gap-1", className)}>
      <View className="flex-row h-2 w-full overflow-hidden rounded-full bg-white/5">
        <View
          className="bg-spredd-green rounded-l-full"
          style={{ width: `${yesPercent}%` }}
        />
        <View
          className="bg-spredd-red rounded-r-full"
          style={{ width: `${noPercent}%` }}
        />
      </View>
      {showLabels && (
        <View className="flex-row justify-between">
          <Text className="text-xs font-medium text-spredd-green">
            Yes {Math.round(yesPercent)}%
          </Text>
          <Text className="text-xs font-medium text-spredd-red">
            No {Math.round(noPercent)}%
          </Text>
        </View>
      )}
    </View>
  );
}
