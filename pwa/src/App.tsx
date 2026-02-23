import { Routes, Route } from "react-router-dom";
import { AuthContext, useAuthProvider } from "@/hooks/useAuth";
import { TelegramAuth } from "@/auth/TelegramAuth";
import { BottomNav } from "@/components/BottomNav";
import { FeedPage } from "@/pages/FeedPage";
import { PortfolioPage } from "@/pages/PortfolioPage";
import { ProfilePage } from "@/pages/ProfilePage";
import { Loader2 } from "lucide-react";

// TODO: Remove DEV_BYPASS_AUTH when Telegram Login Widget is configured
const DEV_BYPASS_AUTH = true;

export default function App() {
  const auth = useAuthProvider();

  if (!DEV_BYPASS_AUTH && auth.loading) {
    return (
      <div className="h-[100dvh] flex items-center justify-center bg-spredd-black">
        <Loader2 className="w-8 h-8 animate-spin text-spredd-orange" />
      </div>
    );
  }

  if (!DEV_BYPASS_AUTH && !auth.authenticated) {
    return (
      <AuthContext.Provider value={auth}>
        <TelegramAuth />
      </AuthContext.Provider>
    );
  }

  return (
    <AuthContext.Provider value={auth}>
      <div className="relative">
        <Routes>
          <Route path="/" element={<FeedPage />} />
          <Route path="/portfolio" element={<PortfolioPage />} />
          <Route path="/profile" element={<ProfilePage />} />
        </Routes>
        <BottomNav />
      </div>
    </AuthContext.Provider>
  );
}
