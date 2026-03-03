import React, { useState } from "react";
import { View, Text, Pressable } from "react-native";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ArrowLeft } from "lucide-react-native";
import { useAuth } from "@/hooks/useAuth";

export default function SignupPage() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { loginWithWallet } = useAuth();
  const [address, setAddress] = useState("");

  const handleConnect = async () => {
    if (!address.trim()) return;
    try {
      await loginWithWallet(address.trim(), "mock_signature");
      router.replace("/(auth)/account-creating");
    } catch {}
  };

  return (
    <View
      className="flex-1 bg-spredd-bg px-6"
      style={{ paddingTop: insets.top, paddingBottom: insets.bottom }}
    >
      <Pressable
        onPress={() => router.back()}
        className="w-10 h-10 items-center justify-center mt-4"
      >
        <ArrowLeft size={24} color="white" />
      </Pressable>

      <View className="flex-1 justify-center gap-6">
        <View className="gap-2">
          <Text className="text-2xl font-bold text-white">
            Connect your wallet
          </Text>
          <Text className="text-sm text-white/50">
            Enter your wallet address to create an account
          </Text>
        </View>

        <Input
          value={address}
          onChangeText={setAddress}
          placeholder="0x... or wallet address"
          autoCapitalize="none"
          autoCorrect={false}
        />

        <Button
          variant="default"
          size="lg"
          onPress={handleConnect}
          disabled={!address.trim()}
        >
          Create Account
        </Button>
      </View>
    </View>
  );
}
