import { useEffect } from "react";
import { Redirect } from "expo-router";
import { useAuth } from "@/hooks/useAuth";

// Dev bypass auth — set to false for production
const DEV_BYPASS_AUTH = true;

export default function Index() {
  const { authenticated, isOnboarded } = useAuth();

  if (DEV_BYPASS_AUTH || authenticated) {
    return <Redirect href="/(tabs)" />;
  }

  if (!isOnboarded) {
    return <Redirect href="/(auth)/welcome" />;
  }

  return <Redirect href="/(auth)/login" />;
}
