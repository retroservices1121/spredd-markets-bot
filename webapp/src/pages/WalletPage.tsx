import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Wallet, Copy, ExternalLink, RefreshCw } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { useTelegram } from "@/contexts/TelegramContext";
import { getWalletBalances } from "@/lib/api";
import { formatUSD, shortenAddress, getChainName, getTokenSymbol } from "@/lib/utils";
import { toast } from "sonner";

export default function WalletPage() {
  const { initData, hapticFeedback } = useTelegram();

  const {
    data,
    isLoading,
    refetch,
    isRefetching,
  } = useQuery({
    queryKey: ["wallet-balances"],
    queryFn: () => getWalletBalances(initData),
  });

  const handleCopyAddress = (address: string) => {
    navigator.clipboard.writeText(address);
    hapticFeedback("light");
    toast.success("Address copied!");
  };

  const handleRefresh = () => {
    hapticFeedback("light");
    refetch();
  };

  // Calculate total balance across all wallets (sum all USDC-like tokens)
  const totalUSDC =
    data?.wallets.reduce((total, wallet) => {
      return total + wallet.balances.reduce((walletTotal, b) => {
        const symbol = getTokenSymbol(b.token);
        // Include USDC, USDC.e, and similar stablecoins
        if (symbol.includes("USDC") || symbol.includes("USD")) {
          return walletTotal + parseFloat(b.amount || "0");
        }
        return walletTotal;
      }, 0);
    }, 0) || 0;

  return (
    <div className="p-4 space-y-4">
      {/* Total Balance Card */}
      <motion.div
        initial={{ opacity: 0, scale: 0.95 }}
        animate={{ opacity: 1, scale: 1 }}
      >
        <Card className="bg-gradient-to-br from-spredd-orange/20 to-orange-900/20 border-spredd-orange/30">
          <CardContent className="p-6">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm text-white/60">Total Balance</span>
              <Button
                variant="ghost"
                size="icon"
                onClick={handleRefresh}
                disabled={isRefetching}
              >
                <RefreshCw
                  className={`w-4 h-4 ${isRefetching ? "animate-spin" : ""}`}
                />
              </Button>
            </div>
            {isLoading ? (
              <Skeleton className="h-10 w-32" />
            ) : (
              <div className="text-3xl font-bold text-white">
                {formatUSD(totalUSDC)}
              </div>
            )}
            <p className="text-xs text-white/40 mt-1">
              Combined USDC across all chains
            </p>
          </CardContent>
        </Card>
      </motion.div>

      {/* Wallet List */}
      <div className="space-y-3">
        <h2 className="text-sm font-medium text-white/60 flex items-center gap-2">
          <Wallet className="w-4 h-4" />
          Your Wallets
        </h2>

        {isLoading ? (
          <>
            <Skeleton className="h-32 w-full rounded-xl" />
            <Skeleton className="h-32 w-full rounded-xl" />
          </>
        ) : data?.wallets && data.wallets.length > 0 ? (
          data.wallets.map((wallet, index) => (
            <motion.div
              key={wallet.public_key}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.1 }}
            >
              <Card>
                <CardHeader className="pb-2">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-base capitalize">
                      {wallet.chain_family === "evm"
                        ? "EVM Wallet"
                        : "Solana Wallet"}
                    </CardTitle>
                    <Badge
                      variant={
                        wallet.chain_family === "evm" ? "polymarket" : "kalshi"
                      }
                    >
                      {wallet.chain_family === "evm"
                        ? "Polygon + BSC"
                        : "Solana"}
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3">
                  {/* Address */}
                  <div className="flex items-center gap-2 bg-spredd-dark rounded-lg p-3">
                    <code className="text-sm text-white/80 flex-1 font-mono truncate">
                      {shortenAddress(wallet.public_key, 6)}
                    </code>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 shrink-0"
                      onClick={() => handleCopyAddress(wallet.public_key)}
                    >
                      <Copy className="w-4 h-4" />
                    </Button>
                  </div>

                  {/* Balances - grouped by chain */}
                  <div className="space-y-2">
                    {/* Group balances by chain */}
                    {(() => {
                      const chainGroups: Record<string, typeof wallet.balances> = {};
                      wallet.balances.forEach((b) => {
                        const chain = getChainName(b.chain) || "Unknown";
                        if (!chainGroups[chain]) chainGroups[chain] = [];
                        chainGroups[chain].push(b);
                      });

                      return Object.entries(chainGroups).map(([chain, balances]) => (
                        <div key={chain} className="space-y-1">
                          {chain && (
                            <p className="text-xs text-white/40 font-medium mt-2">
                              {chain}
                            </p>
                          )}
                          {balances.map((balance) => {
                            const symbol = getTokenSymbol(balance.token, balance.chain);
                            return (
                              <div
                                key={`${balance.chain}-${balance.token}`}
                                className="flex items-center justify-between py-2 border-b border-border last:border-0"
                              >
                                <div className="flex items-center gap-2">
                                  <div className="w-8 h-8 rounded-full bg-spredd-dark flex items-center justify-center text-xs font-bold">
                                    {symbol.slice(0, 2).toUpperCase()}
                                  </div>
                                  <div>
                                    <p className="text-sm font-medium">{symbol}</p>
                                  </div>
                                </div>
                                <div className="text-right">
                                  <p className="font-medium">
                                    {parseFloat(balance.amount).toFixed(4)}
                                  </p>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      ));
                    })()}
                  </div>
                </CardContent>
              </Card>
            </motion.div>
          ))
        ) : (
          <Card>
            <CardContent className="p-8 text-center">
              <Wallet className="w-12 h-12 text-white/20 mx-auto mb-3" />
              <p className="text-white/60 mb-4">No wallets found</p>
              <p className="text-sm text-white/40">
                Send /start to the bot to create your wallets
              </p>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Deposit Instructions */}
      <Card className="border-dashed">
        <CardContent className="p-4">
          <h3 className="font-medium mb-2 flex items-center gap-2">
            <ExternalLink className="w-4 h-4 text-spredd-orange" />
            Deposit Funds
          </h3>
          <p className="text-sm text-white/60">
            Send USDC to your wallet address above. Supported chains:
          </p>
          <div className="flex flex-wrap gap-2 mt-2">
            <Badge variant="outline">Polygon</Badge>
            <Badge variant="outline">Base</Badge>
            <Badge variant="outline">Arbitrum</Badge>
            <Badge variant="outline">Monad</Badge>
            <Badge variant="outline">Solana</Badge>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
