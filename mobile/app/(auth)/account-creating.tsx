import React, { useEffect } from "react";
import { View, Text, ActivityIndicator } from "react-native";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";

export default function AccountCreatingPage() {
  const router = useRouter();
  const insets = useSafeAreaInsets();

  useEffect(() => {
    const timer = setTimeout(() => {
      router.replace("/(tabs)");
    }, 2000);
    return () => clearTimeout(timer);
  }, [router]);

  return (
    <View
      className="flex-1 bg-spredd-bg items-center justify-center px-8"
      style={{ paddingTop: insets.top, paddingBottom: insets.bottom }}
    >
      <ActivityIndicator size="large" color="#00D973" />
      <Text className="text-xl font-bold text-white mt-6">
        Setting up your account...
      </Text>
      <Text className="text-sm text-white/50 mt-2 text-center">
        Creating your wallet and configuring everything
      </Text>
    </View>
  );
}
