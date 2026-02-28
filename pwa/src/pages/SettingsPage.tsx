import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { ArrowLeft, ChevronRight, Shield, Bell, Globe, HelpCircle, LogOut } from "lucide-react";
import { GlassCard } from "@/components/ui/glass-card";
import { Toggle } from "@/components/ui/toggle";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/hooks/useAuth";
import { getUserSettings, updateUserSettings, type UserSettings } from "@/api/client";

export function SettingsPage() {
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const [settings, setSettings] = useState<UserSettings | null>(null);

  useEffect(() => {
    getUserSettings().then(setSettings);
  }, []);

  const update = async (patch: Partial<UserSettings>) => {
    if (!settings) return;
    const next = { ...settings, ...patch };
    setSettings(next);
    try {
      await updateUserSettings(patch);
    } catch {
      // Revert on failure
      setSettings(settings);
    }
  };

  return (
    <div className="min-h-[100dvh] bg-spredd-bg pb-24">
      {/* Header */}
      <div className="sticky top-0 z-30 glass-tab-bar px-5 pt-14 pb-3 flex items-center gap-3">
        <button onClick={() => navigate(-1)} className="text-white/60 hover:text-white">
          <ArrowLeft size={24} />
        </button>
        <h1 className="text-lg font-bold text-white">Settings</h1>
      </div>

      <div className="px-5 pt-4 space-y-5">
        {/* Account */}
        <section>
          <h2 className="text-xs font-medium text-white/40 uppercase tracking-wider mb-2">
            Account
          </h2>
          <GlassCard className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm text-white">Username</span>
              <span className="text-sm text-white/50">
                @{user?.username || "—"}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-white">Platform</span>
              <span className="text-sm text-white/50 capitalize">
                {user?.active_platform || "—"}
              </span>
            </div>
          </GlassCard>
        </section>

        {/* Notifications */}
        {settings && (
          <section>
            <h2 className="text-xs font-medium text-white/40 uppercase tracking-wider mb-2 flex items-center gap-1">
              <Bell size={12} /> Notifications
            </h2>
            <GlassCard className="space-y-4">
              <Toggle
                label="Push Notifications"
                description="Enable all push notifications"
                checked={settings.notifications_enabled}
                onChange={(v) => update({ notifications_enabled: v })}
              />
              <Toggle
                label="Trade Updates"
                description="Order fills and position changes"
                checked={settings.notifications_trades}
                onChange={(v) => update({ notifications_trades: v })}
              />
              <Toggle
                label="Price Alerts"
                description="When markets hit your target price"
                checked={settings.notifications_price_alerts}
                onChange={(v) => update({ notifications_price_alerts: v })}
              />
              <Toggle
                label="Social"
                description="Likes, comments, and follows"
                checked={settings.notifications_social}
                onChange={(v) => update({ notifications_social: v })}
              />
            </GlassCard>
          </section>
        )}

        {/* Security */}
        <section>
          <h2 className="text-xs font-medium text-white/40 uppercase tracking-wider mb-2 flex items-center gap-1">
            <Shield size={12} /> Security
          </h2>
          <GlassCard className="space-y-4">
            {settings && (
              <Toggle
                label="Two-Factor Auth"
                description="Add extra security to your account"
                checked={settings.two_factor_enabled}
                onChange={(v) => update({ two_factor_enabled: v })}
              />
            )}
          </GlassCard>
        </section>

        {/* Preferences */}
        {settings && (
          <section>
            <h2 className="text-xs font-medium text-white/40 uppercase tracking-wider mb-2 flex items-center gap-1">
              <Globe size={12} /> Preferences
            </h2>
            <GlassCard className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-white">Language</span>
                <button className="flex items-center gap-1 text-sm text-white/50">
                  {settings.language === "en" ? "English" : settings.language}
                  <ChevronRight size={14} />
                </button>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-white">Currency</span>
                <button className="flex items-center gap-1 text-sm text-white/50">
                  {settings.currency}
                  <ChevronRight size={14} />
                </button>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-white">Timezone</span>
                <span className="text-sm text-white/50 max-w-[200px] truncate">
                  {settings.timezone}
                </span>
              </div>
            </GlassCard>
          </section>
        )}

        {/* Support */}
        <section>
          <h2 className="text-xs font-medium text-white/40 uppercase tracking-wider mb-2 flex items-center gap-1">
            <HelpCircle size={12} /> Support
          </h2>
          <GlassCard className="space-y-3">
            <button className="flex items-center justify-between w-full">
              <span className="text-sm text-white">Help Center</span>
              <ChevronRight size={14} className="text-white/30" />
            </button>
            <button className="flex items-center justify-between w-full">
              <span className="text-sm text-white">Report a Problem</span>
              <ChevronRight size={14} className="text-white/30" />
            </button>
            <button className="flex items-center justify-between w-full">
              <span className="text-sm text-white">Terms of Service</span>
              <ChevronRight size={14} className="text-white/30" />
            </button>
            <button className="flex items-center justify-between w-full">
              <span className="text-sm text-white">Privacy Policy</span>
              <ChevronRight size={14} className="text-white/30" />
            </button>
          </GlassCard>
        </section>

        {/* Sign Out */}
        <Button
          variant="outline"
          className="w-full border-spredd-red/20 text-spredd-red hover:bg-spredd-red/10"
          onClick={logout}
        >
          <LogOut size={16} />
          Sign Out
        </Button>

        {/* Version */}
        <p className="text-center text-[10px] text-white/20 pb-4">
          Spredd v0.1.0
        </p>
      </div>
    </div>
  );
}
