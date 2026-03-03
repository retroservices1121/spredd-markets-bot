import React, { useEffect } from "react";
import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { useFonts } from "expo-font";
import * as SplashScreen from "expo-splash-screen";
import { AuthContext, useAuthProvider } from "@/hooks/useAuth";
import "../global.css";

SplashScreen.preventAutoHideAsync();

export default function RootLayout() {
  const auth = useAuthProvider();

  const [fontsLoaded] = useFonts({
    Manrope: require("../assets/fonts/Manrope-Regular.ttf"),
    "Manrope-Medium": require("../assets/fonts/Manrope-Medium.ttf"),
    "Manrope-SemiBold": require("../assets/fonts/Manrope-SemiBold.ttf"),
    "Manrope-Bold": require("../assets/fonts/Manrope-Bold.ttf"),
    Bungee: require("../assets/fonts/Bungee-Regular.ttf"),
  });

  useEffect(() => {
    if (fontsLoaded && !auth.loading) {
      SplashScreen.hideAsync();
    }
  }, [fontsLoaded, auth.loading]);

  if (!fontsLoaded || auth.loading) {
    return null;
  }

  return (
    <GestureHandlerRootView style={{ flex: 1, backgroundColor: "#0F0F1A" }}>
      <AuthContext.Provider value={auth}>
        <StatusBar style="light" />
        <Stack
          screenOptions={{
            headerShown: false,
            contentStyle: { backgroundColor: "#0F0F1A" },
            animation: "slide_from_right",
          }}
        >
          <Stack.Screen name="(auth)" />
          <Stack.Screen name="(tabs)" />
          <Stack.Screen name="search" options={{ animation: "fade" }} />
          <Stack.Screen name="settings" />
          <Stack.Screen name="market/[platform]/[marketId]" />
        </Stack>
      </AuthContext.Provider>
    </GestureHandlerRootView>
  );
}
