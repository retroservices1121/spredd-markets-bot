import { lazy, Suspense } from "react";
import { Routes, Route } from "react-router-dom";
import { AuthContext, useAuthProvider } from "@/hooks/useAuth";
import { AppLayout } from "@/components/AppLayout";
import { Loader2 } from "lucide-react";

// Onboarding (not lazy — small, needed fast)
import { WelcomePage } from "@/pages/onboarding/WelcomePage";
import { LoginPage } from "@/pages/onboarding/LoginPage";
import { SignupPage } from "@/pages/onboarding/SignupPage";
import { AccountCreatingPage } from "@/pages/onboarding/AccountCreatingPage";

// Lazy-loaded pages
const HomePage = lazy(() => import("@/pages/HomePage").then((m) => ({ default: m.HomePage })));
const FeedPage = lazy(() => import("@/pages/FeedPage").then((m) => ({ default: m.FeedPage })));
const CreateEventPage = lazy(() => import("@/pages/CreateEventPage").then((m) => ({ default: m.CreateEventPage })));
const RankingPage = lazy(() => import("@/pages/RankingPage").then((m) => ({ default: m.RankingPage })));
const ProfilePage = lazy(() => import("@/pages/ProfilePage").then((m) => ({ default: m.ProfilePage })));
const SearchPage = lazy(() => import("@/pages/SearchPage").then((m) => ({ default: m.SearchPage })));
const SettingsPage = lazy(() => import("@/pages/SettingsPage").then((m) => ({ default: m.SettingsPage })));
const MarketDetailPage = lazy(() => import("@/pages/MarketDetailPage").then((m) => ({ default: m.MarketDetailPage })));

// TODO: Remove DEV_BYPASS_AUTH when Telegram Login Widget is configured
const DEV_BYPASS_AUTH = true;

function PageLoader() {
  return (
    <div className="h-[100dvh] flex items-center justify-center bg-spredd-bg">
      <Loader2 className="w-8 h-8 animate-spin text-spredd-green" />
    </div>
  );
}

export default function App() {
  const auth = useAuthProvider();

  if (!DEV_BYPASS_AUTH && auth.loading) {
    return <PageLoader />;
  }

  return (
    <AuthContext.Provider value={auth}>
      <Suspense fallback={<PageLoader />}>
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
      </Suspense>
    </AuthContext.Provider>
  );
}
