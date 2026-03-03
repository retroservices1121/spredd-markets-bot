import React from "react";
import { View } from "react-native";
import { cn } from "@/lib/utils";

interface GlassCardProps {
  children: React.ReactNode;
  className?: string;
}

export function GlassCard({ children, className }: GlassCardProps) {
  return (
    <View
      className={cn(
        "rounded-2xl border border-white/8 bg-white/[0.06] p-4",
        className
      )}
    >
      {children}
    </View>
  );
}
