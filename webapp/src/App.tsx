import { useState } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/toaster";
import Layout from "@/components/layout/Layout";
import MarketsPage from "@/pages/MarketsPage";
import MarketDetailsPage from "@/pages/MarketDetailsPage";
import WalletPage from "@/pages/WalletPage";
import BridgePage from "@/pages/BridgePage";
import PositionsPage from "@/pages/PositionsPage";
import ProfilePage from "@/pages/ProfilePage";
import WalletSetupPage from "@/pages/WalletSetupPage";
import { useTelegram } from "@/contexts/TelegramContext";
import { getWalletStatus } from "@/lib/api";

function App() {
  const { isReady, initData } = useTelegram();
  const [setupComplete, setSetupComplete] = useState(false);

  // Check wallet status
  const { data: walletStatus, isLoading: walletStatusLoading, refetch } = useQuery({
    queryKey: ["wallet-status"],
    queryFn: () => getWalletStatus(initData),
    enabled: isReady && !!initData,
  });

  // Show loading while Telegram WebApp initializes or checking wallet status
  if (!isReady || walletStatusLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-spredd-black">
        <div className="flex flex-col items-center gap-4">
          <div className="w-12 h-12 border-4 border-spredd-orange border-t-transparent rounded-full animate-spin" />
          <p className="text-white/60 text-sm">Loading Spredd...</p>
        </div>
      </div>
    );
  }

  // Show wallet setup if user doesn't have wallets
  if (walletStatus && !walletStatus.has_wallet && !setupComplete) {
    return (
      <>
        <WalletSetupPage onComplete={() => {
          setSetupComplete(true);
          refetch();
        }} />
        <Toaster />
      </>
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
          <Route path="bridge" element={<BridgePage />} />
          <Route path="positions" element={<PositionsPage />} />
          <Route path="profile" element={<ProfilePage />} />
        </Route>
      </Routes>
      <Toaster />
    </BrowserRouter>
  );
}

export default App;
