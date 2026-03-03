import React, { useState, useEffect, useCallback } from "react";
import {
  View,
  Text,
  ScrollView,
  Pressable,
  ActivityIndicator,
} from "react-native";
import { useRouter } from "expo-router";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { ArrowLeft, ChevronRight } from "lucide-react-native";
import { GlassCard } from "@/components/ui/glass-card";
import { Toggle } from "@/components/ui/toggle";
import {
  getUserSettings,
  updateUserSettings,
  type UserSettings,
} from "@/api/client";

const LANGUAGES = [
  { id: "en", label: "English" },
  { id: "es", label: "Spanish" },
  { id: "fr", label: "French" },
  { id: "pt", label: "Portuguese" },
  { id: "zh", label: "Chinese" },
];

const CURRENCIES = [
  { id: "USD", label: "USD ($)" },
  { id: "EUR", label: "EUR (€)" },
  { id: "GBP", label: "GBP (£)" },
];

export default function SettingsPage() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const [settings, setSettings] = useState<UserSettings | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getUserSettings()
      .then(setSettings)
      .finally(() => setLoading(false));
  }, []);

  const update = useCallback(
    async (patch: Partial<UserSettings>) => {
      if (!settings) return;
      const next = { ...settings, ...patch };
      setSettings(next);
      try {
        await updateUserSettings(patch);
      } catch {
        // Revert on failure
        setSettings(settings);
      }
    },
    [settings]
  );

  if (loading) {
    return (
      <View className="flex-1 bg-spredd-bg items-center justify-center">
        <ActivityIndicator size="large" color="#00D973" />
      </View>
    );
  }

  if (!settings) return null;

  const currentLang =
    LANGUAGES.find((l) => l.id === settings.language)?.label || settings.language;
  const currentCurrency =
    CURRENCIES.find((c) => c.id === settings.currency)?.label || settings.currency;

  const cycleLang = () => {
    const idx = LANGUAGES.findIndex((l) => l.id === settings.language);
    const next = LANGUAGES[(idx + 1) % LANGUAGES.length];
    update({ language: next.id });
  };

  const cycleCurrency = () => {
    const idx = CURRENCIES.findIndex((c) => c.id === settings.currency);
    const next = CURRENCIES[(idx + 1) % CURRENCIES.length];
    update({ currency: next.id });
  };

  return (
    <View className="flex-1 bg-spredd-bg">
      {/* Header */}
      <View
        className="flex-row items-center gap-3 px-5 pb-4 border-b border-white/8"
        style={{ paddingTop: insets.top + 8 }}
      >
        <Pressable onPress={() => router.back()}>
          <ArrowLeft size={22} color="#fff" />
        </Pressable>
        <Text className="text-xl font-bold text-white">Settings</Text>
      </View>

      <ScrollView
        className="flex-1"
        contentContainerStyle={{ padding: 20, paddingBottom: 40 }}
      >
        {/* Notifications */}
        <Text className="text-xs text-white/40 uppercase font-semibold mb-3 tracking-wider">
          Notifications
        </Text>
        <GlassCard className="mb-6">
          <Toggle
            checked={settings.notifications_enabled}
            onChange={(v) => update({ notifications_enabled: v })}
            label="Push Notifications"
            description="Enable all notifications"
            className="mb-4"
          />
          <Toggle
            checked={settings.notifications_trades}
            onChange={(v) => update({ notifications_trades: v })}
            label="Trade Alerts"
            description="Order fills and position updates"
            className="mb-4"
          />
          <Toggle
            checked={settings.notifications_price_alerts}
            onChange={(v) => update({ notifications_price_alerts: v })}
            label="Price Alerts"
            description="Market price movement notifications"
            className="mb-4"
          />
          <Toggle
            checked={settings.notifications_social}
            onChange={(v) => update({ notifications_social: v })}
            label="Social"
            description="Likes, comments, and follows"
          />
        </GlassCard>

        {/* Preferences */}
        <Text className="text-xs text-white/40 uppercase font-semibold mb-3 tracking-wider">
          Preferences
        </Text>
        <GlassCard className="mb-6">
          <Pressable
            onPress={cycleLang}
            className="flex-row items-center justify-between mb-4"
          >
            <View>
              <Text className="text-sm font-medium text-white">Language</Text>
              <Text className="text-xs text-white/40 mt-0.5">
                App display language
              </Text>
            </View>
            <View className="flex-row items-center gap-1">
              <Text className="text-sm text-white/60">{currentLang}</Text>
              <ChevronRight size={16} color="rgba(255,255,255,0.3)" />
            </View>
          </Pressable>

          <Pressable
            onPress={cycleCurrency}
            className="flex-row items-center justify-between"
          >
            <View>
              <Text className="text-sm font-medium text-white">Currency</Text>
              <Text className="text-xs text-white/40 mt-0.5">
                Display currency for values
              </Text>
            </View>
            <View className="flex-row items-center gap-1">
              <Text className="text-sm text-white/60">{currentCurrency}</Text>
              <ChevronRight size={16} color="rgba(255,255,255,0.3)" />
            </View>
          </Pressable>
        </GlassCard>

        {/* Security */}
        <Text className="text-xs text-white/40 uppercase font-semibold mb-3 tracking-wider">
          Security
        </Text>
        <GlassCard>
          <Toggle
            checked={settings.two_factor_enabled}
            onChange={(v) => update({ two_factor_enabled: v })}
            label="Two-Factor Auth"
            description="Extra security for your account"
          />
        </GlassCard>
      </ScrollView>
    </View>
  );
}
