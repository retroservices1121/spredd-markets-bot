import React from "react";
import { TextInput, View, Text, type TextInputProps } from "react-native";
import { cn } from "@/lib/utils";

interface InputProps extends TextInputProps {
  label?: string;
  error?: string;
  containerClassName?: string;
}

export function Input({
  label,
  error,
  className,
  containerClassName,
  ...props
}: InputProps) {
  return (
    <View className={cn("space-y-1", containerClassName)}>
      {label && (
        <Text className="text-sm font-medium text-white mb-1">{label}</Text>
      )}
      <TextInput
        className={cn(
          "h-11 w-full rounded-lg border border-white/10 bg-white/5 px-3 text-sm text-white",
          "placeholder:text-white/40",
          error && "border-spredd-red",
          className
        )}
        placeholderTextColor="rgba(255,255,255,0.4)"
        {...props}
      />
      {error && (
        <Text className="text-xs text-spredd-red mt-1">{error}</Text>
      )}
    </View>
  );
}
