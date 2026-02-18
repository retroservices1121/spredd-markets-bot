import { useState } from "react";
import { useVault } from "@/hooks/useVault";
import { PopupShell } from "@/components/layout/PopupShell";
import type { TabId } from "@/components/layout/BottomNav";
import { OnboardingPage } from "@/pages/OnboardingPage";
import { UnlockPage } from "@/pages/UnlockPage";
import { WalletPage } from "@/pages/WalletPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { MarketsPage } from "@/pages/MarketsPage";
import { MarketDetailPage } from "@/pages/MarketDetailPage";
import { Loader2 } from "lucide-react";

export default function App() {
  const { state, vaultData, error, unlock, lock, refresh } = useVault();
  const [activeTab, setActiveTab] = useState<TabId>("wallet");
  const [selectedEventSlug, setSelectedEventSlug] = useState<string | null>(null);

  // Loading state
  if (state === "loading") {
    return (
      <div className="flex items-center justify-center w-[360px] h-[600px] bg-background">
        <Loader2 className="w-8 h-8 text-spredd-orange animate-spin" />
      </div>
    );
  }

  // No vault — onboarding
  if (state === "no_vault") {
    return (
      <div className="w-[360px] h-[600px] bg-background">
        <OnboardingPage onComplete={refresh} />
      </div>
    );
  }

  // Vault exists but locked
  if (state === "locked" || !vaultData) {
    return (
      <div className="w-[360px] h-[600px] bg-background">
        <UnlockPage onUnlock={unlock} error={error} />
      </div>
    );
  }

  // Render the active tab content
  const renderContent = () => {
    switch (activeTab) {
      case "wallet":
        return <WalletPage vault={vaultData} />;

      case "markets":
        if (selectedEventSlug) {
          return (
            <MarketDetailPage
              slug={selectedEventSlug}
              onBack={() => setSelectedEventSlug(null)}
            />
          );
        }
        return (
          <MarketsPage
            onSelectEvent={(slug) => setSelectedEventSlug(slug)}
          />
        );

      case "settings":
        return <SettingsPage onLock={lock} />;

      default:
        return <WalletPage vault={vaultData} />;
    }
  };

  // Clear detail view when switching away from markets tab
  const handleTabChange = (tab: TabId) => {
    if (tab !== "markets") {
      setSelectedEventSlug(null);
    }
    setActiveTab(tab);
  };

  // Unlocked — main app
  return (
    <PopupShell
      activeTab={activeTab}
      onTabChange={handleTabChange}
      onLock={lock}
    >
      {renderContent()}
    </PopupShell>
  );
}
