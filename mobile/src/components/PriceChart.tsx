import React, { useState } from "react";
import { View, Text, Pressable, Dimensions } from "react-native";
import { cn } from "@/lib/utils";

const { width: SCREEN_WIDTH } = Dimensions.get("window");

interface PriceChartProps {
  data?: Array<{ time: number; value: number }>;
  className?: string;
}

const PERIODS = ["1H", "1D", "1W", "1M", "ALL"] as const;

export function PriceChart({ data, className }: PriceChartProps) {
  const [selectedPeriod, setSelectedPeriod] = useState<string>("1D");

  if (!data || data.length === 0) {
    return (
      <View className={cn("h-48 items-center justify-center", className)}>
        <Text className="text-white/40 text-sm">No chart data available</Text>
      </View>
    );
  }

  // Simple SVG line chart using react-native-svg
  const Svg = require("react-native-svg").default;
  const { Polyline, Defs, LinearGradient, Stop, Rect } =
    require("react-native-svg");

  const chartWidth = SCREEN_WIDTH - 40;
  const chartHeight = 180;
  const padding = 8;

  const values = data.map((d) => d.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const points = data
    .map((d, i) => {
      const x = padding + (i / (data.length - 1)) * (chartWidth - padding * 2);
      const y =
        chartHeight -
        padding -
        ((d.value - min) / range) * (chartHeight - padding * 2);
      return `${x},${y}`;
    })
    .join(" ");

  const lastValue = values[values.length - 1];
  const firstValue = values[0];
  const isUp = lastValue >= firstValue;
  const lineColor = isUp ? "#00D973" : "#FF4059";

  return (
    <View className={cn("", className)}>
      <Svg width={chartWidth} height={chartHeight}>
        <Polyline
          points={points}
          fill="none"
          stroke={lineColor}
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </Svg>

      {/* Period selector */}
      <View className="flex-row justify-between mt-3 px-2">
        {PERIODS.map((period) => (
          <Pressable
            key={period}
            onPress={() => setSelectedPeriod(period)}
            className={cn(
              "px-3 py-1.5 rounded-lg",
              selectedPeriod === period ? "bg-white/10" : ""
            )}
          >
            <Text
              className={cn(
                "text-xs font-medium",
                selectedPeriod === period ? "text-white" : "text-white/40"
              )}
            >
              {period}
            </Text>
          </Pressable>
        ))}
      </View>
    </View>
  );
}
