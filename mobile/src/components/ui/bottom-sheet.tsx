import React, { useCallback, useMemo, useRef, useEffect } from "react";
import { View, Text, Pressable } from "react-native";
import GorhomBottomSheet, {
  BottomSheetBackdrop,
  BottomSheetView,
  type BottomSheetBackdropProps,
} from "@gorhom/bottom-sheet";
import { X } from "lucide-react-native";
import { cn } from "@/lib/utils";

interface BottomSheetProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children: React.ReactNode;
  snapPoints?: (string | number)[];
  className?: string;
}

export function BottomSheet({
  open,
  onClose,
  title,
  children,
  snapPoints: customSnapPoints,
  className,
}: BottomSheetProps) {
  const bottomSheetRef = useRef<GorhomBottomSheet>(null);
  const snapPoints = useMemo(
    () => customSnapPoints || ["50%", "85%"],
    [customSnapPoints]
  );

  useEffect(() => {
    if (open) {
      bottomSheetRef.current?.snapToIndex(0);
    } else {
      bottomSheetRef.current?.close();
    }
  }, [open]);

  const renderBackdrop = useCallback(
    (props: BottomSheetBackdropProps) => (
      <BottomSheetBackdrop
        {...props}
        disappearsOnIndex={-1}
        appearsOnIndex={0}
        opacity={0.6}
      />
    ),
    []
  );

  const handleSheetChanges = useCallback(
    (index: number) => {
      if (index === -1) onClose();
    },
    [onClose]
  );

  return (
    <GorhomBottomSheet
      ref={bottomSheetRef}
      index={open ? 0 : -1}
      snapPoints={snapPoints}
      enablePanDownToClose
      onChange={handleSheetChanges}
      backdropComponent={renderBackdrop}
      handleIndicatorStyle={{ backgroundColor: "rgba(255,255,255,0.2)", width: 40 }}
      backgroundStyle={{ backgroundColor: "#0F0F1A" }}
    >
      <BottomSheetView className={cn("flex-1 px-5", className)}>
        {title && (
          <View className="flex-row items-center justify-between mb-3">
            <Text className="text-lg font-semibold text-white">{title}</Text>
            <Pressable onPress={onClose} className="p-1">
              <X size={20} color="rgba(255,255,255,0.5)" />
            </Pressable>
          </View>
        )}
        {children}
      </BottomSheetView>
    </GorhomBottomSheet>
  );
}
