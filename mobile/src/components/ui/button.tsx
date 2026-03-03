import React from "react";
import { Pressable, Text, ActivityIndicator } from "react-native";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "flex-row items-center justify-center gap-2 rounded-lg active:opacity-80",
  {
    variants: {
      variant: {
        default: "bg-spredd-green",
        destructive: "bg-spredd-red",
        outline: "border border-white/10 bg-transparent",
        secondary: "bg-white/10",
        ghost: "bg-transparent",
        yes: "bg-spredd-green",
        no: "bg-spredd-red",
      },
      size: {
        default: "h-11 px-4 py-2",
        sm: "h-9 px-3",
        lg: "h-14 px-8 rounded-xl",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
);

const textVariants = cva("text-sm font-semibold text-center", {
  variants: {
    variant: {
      default: "text-black",
      destructive: "text-white",
      outline: "text-white",
      secondary: "text-white",
      ghost: "text-white",
      yes: "text-black font-bold",
      no: "text-white font-bold",
    },
    size: {
      default: "text-sm",
      sm: "text-xs",
      lg: "text-lg",
      icon: "text-sm",
    },
  },
  defaultVariants: {
    variant: "default",
    size: "default",
  },
});

export interface ButtonProps extends VariantProps<typeof buttonVariants> {
  children: React.ReactNode;
  onPress?: () => void;
  disabled?: boolean;
  loading?: boolean;
  className?: string;
  textClassName?: string;
}

export function Button({
  children,
  variant,
  size,
  onPress,
  disabled,
  loading,
  className,
  textClassName,
}: ButtonProps) {
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled || loading}
      className={cn(
        buttonVariants({ variant, size }),
        disabled && "opacity-50",
        className
      )}
    >
      {loading ? (
        <ActivityIndicator
          size="small"
          color={variant === "default" || variant === "yes" ? "#000" : "#fff"}
        />
      ) : typeof children === "string" ? (
        <Text className={cn(textVariants({ variant, size }), textClassName)}>
          {children}
        </Text>
      ) : (
        children
      )}
    </Pressable>
  );
}
