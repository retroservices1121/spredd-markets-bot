import React from "react";
import { ScrollView, Pressable, Text } from "react-native";
import { cn } from "@/lib/utils";
import type { Category } from "@/api/client";

interface CategoryPillsProps {
  categories: Category[];
  selected: string;
  onSelect: (id: string) => void;
  className?: string;
}

export function CategoryPills({
  categories,
  selected,
  onSelect,
  className,
}: CategoryPillsProps) {
  return (
    <ScrollView
      horizontal
      showsHorizontalScrollIndicator={false}
      className={cn("", className)}
      contentContainerStyle={{ paddingHorizontal: 16, gap: 8 }}
    >
      {categories.map((cat) => (
        <Pressable
          key={cat.id}
          onPress={() => onSelect(cat.id)}
          className={cn(
            "px-4 py-2 rounded-full border",
            selected === cat.id
              ? "bg-spredd-green border-spredd-green"
              : "bg-transparent border-white/15"
          )}
        >
          <Text
            className={cn(
              "text-sm font-medium",
              selected === cat.id ? "text-black" : "text-white/70"
            )}
          >
            {cat.icon ? `${cat.icon} ` : ""}
            {cat.name}
          </Text>
        </Pressable>
      ))}
    </ScrollView>
  );
}
