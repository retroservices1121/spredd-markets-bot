import { useState, useEffect } from "react";
import { LogOut, Wallet, Copy, Check, ExternalLink } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth } from "@/hooks/useAuth";
import { getBalances, type WalletBalance } from "@/api/client";
import { formatUSD, cn } from "@/lib/utils";

export function ProfilePage() {
  const { user, logout } = useAuth();
  const [balances, setBalances] = useState<WalletBalance[]>([]);
  const [loadingBalances, setLoadingBalances] = useState(true);
  const [copiedAddress, setCopiedAddress] = useState<string | null>(null);

  useEffect(() => {
    getBalances()
      .then((res) => setBalances(res.balances || []))
      .catch(() => {})
      .finally(() => setLoadingBalances(false));
  }, []);

  const copyAddress = async (address: string) => {
    await navigator.clipboard.writeText(address);
    setCopiedAddress(address);
    setTimeout(() => setCopiedAddress(null), 2000);
  };

  return (
    <div className="min-h-[100dvh] bg-spredd-black pb-20 pt-14">
      <div className="px-5 py-4">
        {/* User header */}
        <div className="flex items-center gap-4 mb-6">
          <div className="w-14 h-14 rounded-full bg-spredd-orange/20 flex items-center justify-center">
            <span className="text-2xl font-bold text-spredd-orange">
              {(user?.first_name || user?.username || "U")[0].toUpperCase()}
            </span>
          </div>
          <div>
            <h1 className="text-xl font-bold text-white">
              {user?.first_name || user?.username || "User"}
            </h1>
            {user?.username && (
              <p className="text-white/40 text-sm">@{user.username}</p>
            )}
          </div>
        </div>

        {/* Wallets */}
        <div className="mb-6">
          <h2 className="text-sm font-medium text-white/50 mb-3 flex items-center gap-2">
            <Wallet size={14} /> Wallets
          </h2>

          {loadingBalances && (
            <div className="space-y-3">
              <Skeleton className="h-20 w-full rounded-xl" />
              <Skeleton className="h-20 w-full rounded-xl" />
            </div>
          )}

          {!loadingBalances && balances.length === 0 && (
            <Card className="bg-spredd-dark border-white/5">
              <CardContent className="p-4 text-center">
                <p className="text-white/40 text-sm">No wallets found</p>
                <p className="text-white/25 text-xs mt-1">
                  Start the Spredd Telegram bot to set up your wallets
                </p>
              </CardContent>
            </Card>
          )}

          <div className="space-y-3">
            {balances.map((wallet) => {
              const totalUsd = wallet.balances.reduce(
                (sum, b) => sum + (parseFloat(b.usd_value || "0") || 0),
                0
              );
              const shortAddr = `${wallet.public_key.slice(0, 6)}...${wallet.public_key.slice(-4)}`;

              return (
                <Card
                  key={wallet.public_key}
                  className="bg-spredd-dark border-white/5"
                >
                  <CardContent className="p-4">
                    <div className="flex items-center justify-between mb-3">
                      <div className="flex items-center gap-2">
                        <Badge variant="platform" className="text-[10px]">
                          {wallet.chain_family}
                        </Badge>
                        <button
                          onClick={() => copyAddress(wallet.public_key)}
                          className="flex items-center gap-1 text-white/60 hover:text-white text-xs transition-colors"
                        >
                          <span className="font-mono">{shortAddr}</span>
                          {copiedAddress === wallet.public_key ? (
                            <Check size={12} className="text-spredd-green" />
                          ) : (
                            <Copy size={12} />
                          )}
                        </button>
                      </div>
                      <span className="text-sm font-bold text-white">
                        {formatUSD(totalUsd)}
                      </span>
                    </div>

                    <div className="space-y-1">
                      {wallet.balances.map((bal) => (
                        <div
                          key={bal.token}
                          className="flex justify-between text-xs text-white/40"
                        >
                          <span>{bal.token}</span>
                          <span>
                            {bal.balance}{" "}
                            {bal.usd_value && (
                              <span className="text-white/25">
                                ({formatUSD(bal.usd_value)})
                              </span>
                            )}
                          </span>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </div>

        {/* Referral code */}
        {user?.referral_code && (
          <Card className="bg-spredd-dark border-white/5 mb-6">
            <CardContent className="p-4">
              <p className="text-xs text-white/50 mb-1">Referral Code</p>
              <div className="flex items-center justify-between">
                <span className="font-mono text-spredd-orange font-bold">
                  {user.referral_code}
                </span>
                <button
                  onClick={() => copyAddress(user.referral_code!)}
                  className="text-white/40 hover:text-white"
                >
                  {copiedAddress === user.referral_code ? (
                    <Check size={14} className="text-spredd-green" />
                  ) : (
                    <Copy size={14} />
                  )}
                </button>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Logout */}
        <Button
          variant="outline"
          className="w-full border-white/10 text-white/60"
          onClick={logout}
        >
          <LogOut size={16} />
          Sign Out
        </Button>
      </div>
    </div>
  );
}
