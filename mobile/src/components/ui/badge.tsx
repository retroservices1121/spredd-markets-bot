import React from "react";
import { View, Text } from "react-native";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "flex-row items-center rounded-full px-2.5 py-0.5",
  {
    variants: {
      variant: {
        default: "bg-spredd-green",
        secondary: "bg-white/10",
        destructive: "bg-spredd-red",
        outline: "border border-white/20",
        success: "bg-spredd-green/20",
        platform: "bg-white/10",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
);

const textVariants = cva("text-xs font-semibold", {
  variants: {
    variant: {
      default: "text-black",
      secondary: "text-white/80",
      destructive: "text-white",
      outline: "text-white",
      success: "text-spredd-green",
      platform: "text-white/90",
    },
  },
  defaultVariants: {
    variant: "default",
  },
});

export interface BadgeProps extends VariantProps<typeof badgeVariants> {
  children: React.ReactNode;
  className?: string;
}

export function Badge({ children, variant, className }: BadgeProps) {
  return (
    <View className={cn(badgeVariants({ variant }), className)}>
      {typeof children === "string" ? (
        <Text className={textVariants({ variant })}>{children}</Text>
      ) : (
        children
      )}
    </View>
  );
}
