import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "@/components/ui/toaster";
import Layout from "@/components/layout/Layout";
import MarketsPage from "@/pages/MarketsPage";
import MarketDetailsPage from "@/pages/MarketDetailsPage";
import WalletPage from "@/pages/WalletPage";
import PositionsPage from "@/pages/PositionsPage";
import ProfilePage from "@/pages/ProfilePage";
import { useTelegram } from "@/contexts/TelegramContext";

function App() {
  const { isReady, user } = useTelegram();

  // Show loading while Telegram WebApp initializes
  if (!isReady) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-spredd-black">
        <div className="flex flex-col items-center gap-4">
          <div className="w-12 h-12 border-4 border-spredd-orange border-t-transparent rounded-full animate-spin" />
          <p className="text-white/60 text-sm">Loading Spredd...</p>
        </div>
      </div>
    );
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Navigate to="/markets" replace />} />
          <Route path="markets" element={<MarketsPage />} />
          <Route path="markets/:platform/:marketId" element={<MarketDetailsPage />} />
          <Route path="wallet" element={<WalletPage />} />
          <Route path="positions" element={<PositionsPage />} />
          <Route path="profile" element={<ProfilePage />} />
        </Route>
      </Routes>
      <Toaster />
    </BrowserRouter>
  );
}

export default App;
