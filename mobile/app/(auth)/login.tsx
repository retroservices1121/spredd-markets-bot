import React from "react";
import { View, Text, Pressable, Linking } from "react-native";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Button } from "@/components/ui/button";
import { MessageCircle, Wallet, ArrowLeft } from "lucide-react-native";

export default function LoginPage() {
  const router = useRouter();
  const insets = useSafeAreaInsets();

  const handleTelegramLogin = () => {
    // Open Telegram bot deep link for auth
    Linking.openURL("https://t.me/SpreddBot?start=login");
  };

  return (
    <View
      className="flex-1 bg-spredd-bg px-6"
      style={{ paddingTop: insets.top, paddingBottom: insets.bottom }}
    >
      {/* Back button */}
      <Pressable
        onPress={() => router.back()}
        className="w-10 h-10 items-center justify-center mt-4"
      >
        <ArrowLeft size={24} color="white" />
      </Pressable>

      {/* Content */}
      <View className="flex-1 justify-center gap-8">
        <View className="items-center gap-4">
          <Text className="font-brand text-3xl text-spredd-green">SPREDD</Text>
          <Text className="text-base text-white/60 text-center">
            Sign in to start trading on prediction markets
          </Text>
        </View>

        <View className="gap-3">
          {/* Telegram login */}
          <Button variant="default" size="lg" onPress={handleTelegramLogin}>
            <View className="flex-row items-center gap-3">
              <MessageCircle size={20} color="black" />
              <Text className="text-black font-bold text-base">
                Continue with Telegram
              </Text>
            </View>
          </Button>

          {/* Wallet login */}
          <Button
            variant="outline"
            size="lg"
            onPress={() => router.push("/(auth)/signup")}
          >
            <View className="flex-row items-center gap-3">
              <Wallet size={20} color="white" />
              <Text className="text-white font-medium text-base">
                Connect Wallet
              </Text>
            </View>
          </Button>
        </View>
      </View>

      {/* Footer */}
      <Text className="text-xs text-white/30 text-center pb-4">
        By continuing, you agree to our Terms of Service
      </Text>
    </View>
  );
}
