import { Routes, Route } from "react-router-dom";
import { AuthContext, useAuthProvider } from "@/hooks/useAuth";
import { AppLayout } from "@/components/AppLayout";
import { Loader2 } from "lucide-react";

// Onboarding
import { WelcomePage } from "@/pages/onboarding/WelcomePage";
import { LoginPage } from "@/pages/onboarding/LoginPage";
import { SignupPage } from "@/pages/onboarding/SignupPage";
import { AccountCreatingPage } from "@/pages/onboarding/AccountCreatingPage";

// Pages
import { HomePage } from "@/pages/HomePage";
import { FeedPage } from "@/pages/FeedPage";
import { CreateEventPage } from "@/pages/CreateEventPage";
import { RankingPage } from "@/pages/RankingPage";
import { ProfilePage } from "@/pages/ProfilePage";
import { SearchPage } from "@/pages/SearchPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { MarketDetailPage } from "@/pages/MarketDetailPage";

// TODO: Remove DEV_BYPASS_AUTH when Telegram Login Widget is configured
const DEV_BYPASS_AUTH = true;

export default function App() {
  const auth = useAuthProvider();

  if (!DEV_BYPASS_AUTH && auth.loading) {
    return (
      <div className="h-[100dvh] flex items-center justify-center bg-spredd-bg">
        <Loader2 className="w-8 h-8 animate-spin text-spredd-green" />
      </div>
    );
  }

  return (
    <AuthContext.Provider value={auth}>
      <Routes>
        {/* Onboarding (no layout wrapper) */}
        <Route path="/welcome" element={<WelcomePage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/signup" element={<SignupPage />} />
        <Route path="/account-creating" element={<AccountCreatingPage />} />

        {/* Feed — full-screen, no bottom nav */}
        <Route path="/feed" element={<FeedPage />} />

        {/* Market detail — full-screen */}
        <Route path="/market/:platform/:marketId" element={<MarketDetailPage />} />

        {/* Authenticated routes with bottom nav */}
        <Route element={<AppLayout />}>
          <Route path="/" element={<HomePage />} />
          <Route path="/create" element={<CreateEventPage />} />
          <Route path="/ranking" element={<RankingPage />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Route>
      </Routes>
    </AuthContext.Provider>
  );
}
