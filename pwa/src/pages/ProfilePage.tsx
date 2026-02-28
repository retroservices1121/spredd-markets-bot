import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Settings, Plus, Minus, TrendingUp, TrendingDown, Loader2 } from "lucide-react";
import { Avatar } from "@/components/ui/avatar";
import { GlassCard } from "@/components/ui/glass-card";
import { Tabs } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { DepositSheet } from "@/components/DepositSheet";
import { WithdrawSheet } from "@/components/WithdrawSheet";
import { useProfileStats } from "@/hooks/useProfileStats";
import { useAuth } from "@/hooks/useAuth";
import { formatUSD, formatPercent, platformLabel, cn } from "@/lib/utils";

const PROFILE_TABS = [
  { id: "active", label: "Active" },
  { id: "history", label: "History" },
  { id: "bookmarks", label: "Bookmarks" },
  { id: "following", label: "Following" },
];

export function ProfilePage() {
  const navigate = useNavigate();
  const { logout } = useAuth();
  const { user, balances, positions, pnl, loading } = useProfileStats();
  const [activeTab, setActiveTab] = useState("active");
  const [depositOpen, setDepositOpen] = useState(false);
  const [withdrawOpen, setWithdrawOpen] = useState(false);

  const totalBalance = balances.reduce(
    (sum, w) =>
      sum + w.balances.reduce((s, b) => s + (parseFloat(b.usd_value || "0") || 0), 0),
    0
  );

  if (loading) {
    return (
      <div className="min-h-[100dvh] bg-spredd-bg pb-24 pt-14 px-5">
        <div className="flex items-center gap-4 mb-6 pt-4">
          <Skeleton className="w-16 h-16 rounded-full" />
          <div className="space-y-2">
            <Skeleton className="w-32 h-5" />
            <Skeleton className="w-20 h-4" />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3 mb-5">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-20 rounded-xl" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="min-h-[100dvh] bg-spredd-bg pb-24 mesh-gradient-profile">
        {/* Header */}
        <div className="sticky top-0 z-30 glass-tab-bar px-5 pt-14 pb-3 flex items-center justify-between">
          <h1 className="text-lg font-bold text-white">Profile</h1>
          <button
            onClick={() => navigate("/settings")}
            className="text-white/60 hover:text-white"
          >
            <Settings size={22} />
          </button>
        </div>

        <div className="px-5 pt-4 space-y-5">
          {/* User info */}
          <div className="flex items-center gap-4">
            <Avatar
              src={user?.avatar}
              name={user?.first_name || user?.username}
              size="xl"
            />
            <div>
              <h2 className="text-xl font-bold text-white">
                {user?.first_name || user?.username || "User"}
              </h2>
              {user?.username && (
                <p className="text-white/40 text-sm">@{user.username}</p>
              )}
            </div>
          </div>

          {/* Stats grid */}
          <div className="grid grid-cols-2 gap-3">
            <GlassCard className="text-center">
              <p className="text-2xl font-bold text-spredd-green">
                {pnl ? `${Math.round(pnl.win_rate * 100)}%` : "—"}
              </p>
              <p className="text-xs text-white/40 mt-1">Win Rate</p>
            </GlassCard>
            <GlassCard className="text-center">
              <p className={cn(
                "text-2xl font-bold",
                (pnl?.total_pnl ?? 0) >= 0 ? "text-spredd-green" : "text-spredd-red"
              )}>
                {pnl ? `${(pnl.total_pnl >= 0 ? "+" : "")}${formatUSD(pnl.total_pnl)}` : "—"}
              </p>
              <p className="text-xs text-white/40 mt-1">Profit</p>
            </GlassCard>
            <GlassCard className="text-center">
              <p className="text-2xl font-bold text-white">
                {pnl?.active_positions ?? 0}
              </p>
              <p className="text-xs text-white/40 mt-1">Active</p>
            </GlassCard>
            <GlassCard className="text-center">
              <p className="text-2xl font-bold text-white">
                {pnl?.win_streak ?? 0}
              </p>
              <p className="text-xs text-white/40 mt-1">Win Streak</p>
            </GlassCard>
          </div>

          {/* Balance card */}
          <GlassCard>
            <div className="flex items-center justify-between mb-3">
              <div>
                <p className="text-xs text-white/40">Total Balance</p>
                <p className="text-2xl font-bold text-white">{formatUSD(totalBalance)}</p>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => setDepositOpen(true)}
                  className="w-10 h-10 rounded-full bg-spredd-green/15 flex items-center justify-center text-spredd-green"
                >
                  <Plus size={18} />
                </button>
                <button
                  onClick={() => setWithdrawOpen(true)}
                  className="w-10 h-10 rounded-full bg-white/10 flex items-center justify-center text-white/60"
                >
                  <Minus size={18} />
                </button>
              </div>
            </div>
            {/* Wallet chips */}
            <div className="flex gap-2 flex-wrap">
              {balances.map((w) => (
                <span
                  key={w.public_key}
                  className="text-[10px] bg-white/6 text-white/50 px-2 py-0.5 rounded-full"
                >
                  {w.chain_family}: {w.public_key.slice(0, 6)}...{w.public_key.slice(-4)}
                </span>
              ))}
            </div>
          </GlassCard>

          {/* Tabs */}
          <Tabs
            tabs={PROFILE_TABS}
            activeTab={activeTab}
            onTabChange={setActiveTab}
          />

          {/* Tab content */}
          <div className="space-y-3">
            {activeTab === "active" && (
              <>
                {positions.length === 0 && (
                  <div className="text-center py-8">
                    <p className="text-white/40 text-sm">No active positions</p>
                    <p className="text-white/25 text-xs mt-1">
                      Start trading from the feed
                    </p>
                  </div>
                )}
                {positions.map((pos) => {
                  const isProfit = pos.pnl >= 0;
                  return (
                    <GlassCard key={pos.id} className="flex items-center justify-between">
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-white truncate">
                          {pos.market_title}
                        </p>
                        <div className="flex items-center gap-2 mt-1">
                          <Badge variant="platform" className="text-[10px]">
                            {platformLabel(pos.platform)}
                          </Badge>
                          <span
                            className={cn(
                              "text-[10px] font-bold px-2 py-0.5 rounded-full",
                              pos.outcome.toLowerCase() === "yes"
                                ? "bg-spredd-green/20 text-spredd-green"
                                : "bg-spredd-red/20 text-spredd-red"
                            )}
                          >
                            {pos.outcome}
                          </span>
                        </div>
                      </div>
                      <div className="text-right shrink-0 ml-3">
                        <div className="flex items-center gap-1 justify-end">
                          {isProfit ? (
                            <TrendingUp size={12} className="text-spredd-green" />
                          ) : (
                            <TrendingDown size={12} className="text-spredd-red" />
                          )}
                          <span
                            className={cn(
                              "text-sm font-bold",
                              isProfit ? "text-spredd-green" : "text-spredd-red"
                            )}
                          >
                            {isProfit ? "+" : ""}{formatUSD(pos.pnl)}
                          </span>
                        </div>
                      </div>
                    </GlassCard>
                  );
                })}
              </>
            )}

            {activeTab === "history" && (
              <div className="text-center py-8">
                <p className="text-white/40 text-sm">Trade history coming soon</p>
              </div>
            )}

            {activeTab === "bookmarks" && (
              <div className="text-center py-8">
                <p className="text-white/40 text-sm">No bookmarks yet</p>
                <p className="text-white/25 text-xs mt-1">
                  Bookmark markets from the feed
                </p>
              </div>
            )}

            {activeTab === "following" && (
              <div className="text-center py-8">
                <p className="text-white/40 text-sm">Not following anyone yet</p>
              </div>
            )}
          </div>

          {/* Sign out */}
          <Button
            variant="outline"
            className="w-full border-white/10 text-white/40"
            onClick={logout}
          >
            Sign Out
          </Button>
        </div>
      </div>

      {/* Sheets */}
      <DepositSheet open={depositOpen} onClose={() => setDepositOpen(false)} wallets={balances} />
      <WithdrawSheet open={withdrawOpen} onClose={() => setWithdrawOpen(false)} wallets={balances} />
    </>
  );
}
