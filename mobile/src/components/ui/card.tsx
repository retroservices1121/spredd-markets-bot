import React from "react";
import { View, Text } from "react-native";
import { cn } from "@/lib/utils";

interface CardProps {
  children: React.ReactNode;
  className?: string;
}

export function Card({ children, className }: CardProps) {
  return (
    <View
      className={cn(
        "rounded-xl border border-white/8 bg-white/[0.06]",
        className
      )}
    >
      {children}
    </View>
  );
}

export function CardHeader({ children, className }: CardProps) {
  return (
    <View className={cn("flex-col gap-1.5 p-4", className)}>{children}</View>
  );
}

export function CardTitle({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <Text className={cn("font-semibold leading-none text-white", className)}>
      {typeof children === "string" ? children : ""}
    </Text>
  );
}

export function CardDescription({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <Text className={cn("text-sm text-white/50", className)}>
      {typeof children === "string" ? children : ""}
    </Text>
  );
}

export function CardContent({ children, className }: CardProps) {
  return <View className={cn("p-4 pt-0", className)}>{children}</View>;
}

export function CardFooter({ children, className }: CardProps) {
  return (
    <View className={cn("flex-row items-center p-4 pt-0", className)}>
      {children}
    </View>
  );
}
