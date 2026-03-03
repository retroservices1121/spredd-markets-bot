import React from "react";
import { View, Text } from "react-native";
import RNSlider from "@react-native-community/slider";
import { cn } from "@/lib/utils";

interface SliderProps {
  min: number;
  max: number;
  step?: number;
  value: number;
  onChange: (value: number) => void;
  formatLabel?: (value: number) => string;
  className?: string;
}

export function Slider({
  min,
  max,
  step = 1,
  value,
  onChange,
  formatLabel,
  className,
}: SliderProps) {
  return (
    <View className={cn("gap-2", className)}>
      <RNSlider
        minimumValue={min}
        maximumValue={max}
        step={step}
        value={value}
        onValueChange={onChange}
        minimumTrackTintColor="#00D973"
        maximumTrackTintColor="rgba(255,255,255,0.1)"
        thumbTintColor="#00D973"
        style={{ width: "100%", height: 40 }}
      />
      {formatLabel && (
        <Text className="text-center text-sm font-medium text-white">
          {formatLabel(value)}
        </Text>
      )}
    </View>
  );
}
