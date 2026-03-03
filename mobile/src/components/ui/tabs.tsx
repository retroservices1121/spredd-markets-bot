import React, { useEffect, useRef } from "react";
import { View, Pressable, Text, LayoutChangeEvent } from "react-native";
import Animated, {
  useSharedValue,
  useAnimatedStyle,
  withTiming,
} from "react-native-reanimated";
import { cn } from "@/lib/utils";

interface Tab {
  id: string;
  label: string;
}

interface TabsProps {
  tabs: Tab[];
  activeTab: string;
  onTabChange: (id: string) => void;
  className?: string;
}

export function Tabs({ tabs, activeTab, onTabChange, className }: TabsProps) {
  const layouts = useRef<Record<string, { x: number; width: number }>>({});
  const indicatorX = useSharedValue(0);
  const indicatorW = useSharedValue(0);

  const updateIndicator = (tabId: string) => {
    const layout = layouts.current[tabId];
    if (layout) {
      indicatorX.value = withTiming(layout.x, { duration: 200 });
      indicatorW.value = withTiming(layout.width, { duration: 200 });
    }
  };

  useEffect(() => {
    updateIndicator(activeTab);
  }, [activeTab]);

  const indicatorStyle = useAnimatedStyle(() => ({
    transform: [{ translateX: indicatorX.value }],
    width: indicatorW.value,
  }));

  const handleLayout = (tabId: string) => (e: LayoutChangeEvent) => {
    const { x, width } = e.nativeEvent.layout;
    layouts.current[tabId] = { x, width };
    if (tabId === activeTab) {
      updateIndicator(tabId);
    }
  };

  return (
    <View className={cn("relative flex-row bg-white/5 rounded-xl p-1", className)}>
      <Animated.View
        style={indicatorStyle}
        className="absolute top-1 h-[calc(100%-8px)] bg-spredd-green/20 rounded-lg"
      />
      {tabs.map((tab) => (
        <Pressable
          key={tab.id}
          onPress={() => onTabChange(tab.id)}
          onLayout={handleLayout(tab.id)}
          className="flex-1 py-2 px-3 items-center z-10"
        >
          <Text
            className={cn(
              "text-sm font-medium",
              activeTab === tab.id ? "text-spredd-green" : "text-white/50"
            )}
          >
            {tab.label}
          </Text>
        </Pressable>
      ))}
    </View>
  );
}
