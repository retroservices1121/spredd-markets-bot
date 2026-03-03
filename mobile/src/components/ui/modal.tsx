import React from "react";
import {
  Modal as RNModal,
  View,
  Text,
  Pressable,
  KeyboardAvoidingView,
  Platform,
} from "react-native";
import { X } from "lucide-react-native";
import { cn } from "@/lib/utils";

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: React.ReactNode;
  className?: string;
}

export function Modal({ open, onClose, title, children, className }: ModalProps) {
  return (
    <RNModal
      visible={open}
      transparent
      animationType="fade"
      onRequestClose={onClose}
      statusBarTranslucent
    >
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : "height"}
        className="flex-1"
      >
        <Pressable
          onPress={onClose}
          className="flex-1 items-center justify-center px-6 bg-black/70"
        >
          <Pressable
            onPress={(e) => e.stopPropagation()}
            className={cn(
              "w-full max-w-sm bg-spredd-bg rounded-2xl p-6 border border-white/8",
              className
            )}
          >
            {title && (
              <View className="flex-row items-center justify-between mb-4">
                <Text className="text-lg font-semibold text-white">
                  {title}
                </Text>
                <Pressable onPress={onClose} className="p-1">
                  <X size={20} color="rgba(255,255,255,0.5)" />
                </Pressable>
              </View>
            )}
            {children}
          </Pressable>
        </Pressable>
      </KeyboardAvoidingView>
    </RNModal>
  );
}
