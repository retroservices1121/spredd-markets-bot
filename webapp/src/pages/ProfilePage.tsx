import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import {
  User,
  Share2,
  Copy,
  ChevronRight,
  ChevronDown,
  MessageCircle,
  HelpCircle,
  ExternalLink,
  X,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useTelegram } from "@/contexts/TelegramContext";
import { getCurrentUser, getReferralStats } from "@/lib/api";
import { formatUSD, getPlatformName } from "@/lib/utils";
import { toast } from "sonner";

const FAQ_ITEMS = [
  {
    q: "Is this non-custodial?",
    a: "Yes, Spredd is non-custodial. Your private keys are encrypted and stored securely. Only YOU can export your keys using your PIN. We cannot access your private keys or export your wallet.",
  },
  {
    q: "Why do I need a PIN?",
    a: "Your PIN protects your private key export. It ensures only YOU can export your wallet's private keys. Trading doesn't require PIN entry (for convenience), but exporting keys requires your PIN (for security).",
  },
  {
    q: "What are the fees?",
    a: "Spredd charges 1% on all trades. No deposit/withdrawal fees. Platform fees vary by market. Network gas fees are minimal (SOL ~$0.001, Polygon ~$0.01, BSC ~$0.10).",
  },
  {
    q: "How do I deposit?",
    a: "Go to the Wallet tab to see your addresses. Send USDC to your Solana address for Kalshi, or your EVM address for Polymarket (Polygon), Opinion Labs (BSC), and Monad. Don't forget gas tokens (SOL, MATIC, BNB, MON).",
  },
  {
    q: "What is USDC Auto-Swap?",
    a: "Polymarket requires USDC.e (bridged USDC). The bot automatically swaps your native USDC to USDC.e via Uniswap when needed, so you can trade seamlessly.",
  },
  {
    q: "How does Cross-Chain Bridging work?",
    a: "Have USDC on Base, Arbitrum, or other chains? Use the bridge feature to move it to Polygon for Polymarket. Fast Bridge (~30 sec, small fee) or Standard Bridge (~15 min, free via Circle CCTP).",
  },
  {
    q: "Security tips?",
    a: "Never share your PIN or private keys. We will NEVER DM you first or ask for your PIN. Always verify addresses before depositing. Start with small amounts to test.",
  },
];

export default function ProfilePage() {
  const { user: tgUser, initData, hapticFeedback, close } = useTelegram();
  const [showHelp, setShowHelp] = useState(false);
  const [expandedFaq, setExpandedFaq] = useState<number | null>(null);

  // Fetch user info
  const { data: userData, isLoading: userLoading } = useQuery({
    queryKey: ["user"],
    queryFn: () => getCurrentUser(initData),
  });

  // Fetch referral stats
  const { data: referralData, isLoading: referralLoading } = useQuery({
    queryKey: ["referral-stats"],
    queryFn: () => getReferralStats(initData),
  });

  const handleCopyReferral = () => {
    if (referralData?.referral_code) {
      navigator.clipboard.writeText(
        `https://t.me/spreddbot?start=${referralData.referral_code}`
      );
      hapticFeedback("light");
      toast.success("Referral link copied!");
    }
  };

  const totalEarned =
    referralData?.fee_balances.reduce(
      (sum, fb) => sum + parseFloat(fb.total_earned_usdc),
      0
    ) || 0;

  const totalClaimable =
    referralData?.fee_balances.reduce(
      (sum, fb) => sum + parseFloat(fb.claimable_usdc),
      0
    ) || 0;

  return (
    <div className="p-4 space-y-4">
      {/* Profile Header */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
      >
        <Card className="bg-gradient-to-br from-spredd-dark to-spredd-black">
          <CardContent className="p-6">
            <div className="flex items-center gap-4">
              <div className="w-16 h-16 rounded-full bg-spredd-orange/20 flex items-center justify-center">
                {tgUser?.photo_url ? (
                  <img
                    src={tgUser.photo_url}
                    alt={tgUser.first_name}
                    className="w-full h-full rounded-full object-cover"
                  />
                ) : (
                  <User className="w-8 h-8 text-spredd-orange" />
                )}
              </div>
              <div className="flex-1">
                <h2 className="text-xl font-bold">
                  {tgUser?.first_name} {tgUser?.last_name}
                </h2>
                {tgUser?.username && (
                  <p className="text-white/60">@{tgUser.username}</p>
                )}
              </div>
            </div>

            {/* Active Platform */}
            {userLoading ? (
              <Skeleton className="h-6 w-24 mt-4" />
            ) : userData?.active_platform && (
              <div className="mt-4 flex items-center gap-2">
                <span className="text-sm text-white/40">Active Platform:</span>
                <Badge
                  variant={
                    userData.active_platform as
                      | "kalshi"
                      | "polymarket"
                      | "opinion"
                  }
                >
                  {getPlatformName(userData.active_platform)}
                </Badge>
              </div>
            )}
          </CardContent>
        </Card>
      </motion.div>

      {/* Referral Card */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.1 }}
      >
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2">
              <Share2 className="w-4 h-4 text-spredd-orange" />
              Referral Program
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Stats */}
            {referralLoading ? (
              <div className="grid grid-cols-3 gap-3">
                <Skeleton className="h-16 rounded-lg" />
                <Skeleton className="h-16 rounded-lg" />
                <Skeleton className="h-16 rounded-lg" />
              </div>
            ) : (
              <div className="grid grid-cols-3 gap-3">
                <div className="bg-spredd-dark rounded-lg p-3 text-center">
                  <p className="text-2xl font-bold">
                    {referralData?.total_referrals || 0}
                  </p>
                  <p className="text-xs text-white/40">Referrals</p>
                </div>
                <div className="bg-spredd-dark rounded-lg p-3 text-center">
                  <p className="text-2xl font-bold text-spredd-green">
                    {formatUSD(totalEarned)}
                  </p>
                  <p className="text-xs text-white/40">Earned</p>
                </div>
                <div className="bg-spredd-dark rounded-lg p-3 text-center">
                  <p className="text-2xl font-bold text-spredd-orange">
                    {formatUSD(totalClaimable)}
                  </p>
                  <p className="text-xs text-white/40">Claimable</p>
                </div>
              </div>
            )}

            {/* Referral Link */}
            {referralData?.referral_code && (
              <div className="flex items-center gap-2">
                <div className="flex-1 bg-spredd-dark rounded-lg p-3 font-mono text-sm truncate">
                  t.me/spreddbot?start={referralData.referral_code}
                </div>
                <Button
                  variant="outline"
                  size="icon"
                  onClick={handleCopyReferral}
                >
                  <Copy className="w-4 h-4" />
                </Button>
              </div>
            )}

            <p className="text-xs text-white/40 text-center">
              Earn 30% of fees from your referrals' trades
            </p>
          </CardContent>
        </Card>
      </motion.div>

      {/* Menu Items */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
      >
        <Card>
          <CardContent className="p-0 divide-y divide-border">
            <MenuItem
              icon={MessageCircle}
              label="Help"
              description="Get support"
              onClick={() => setShowHelp(true)}
            />
            <MenuItem
              icon={ExternalLink}
              label="Follow Us"
              description="@spreddterminal"
              onClick={() => window.open("https://x.com/spreddterminal", "_blank")}
            />
          </CardContent>
        </Card>
      </motion.div>

      {/* FAQs Section - Always visible */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.3 }}
      >
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2">
              <HelpCircle className="w-4 h-4 text-spredd-orange" />
              FAQs
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {FAQ_ITEMS.map((faq, index) => (
              <div key={index} className="border-b border-border last:border-0 pb-3 last:pb-0">
                <button
                  className="w-full flex items-center justify-between text-left"
                  onClick={() => setExpandedFaq(expandedFaq === index ? null : index)}
                >
                  <span className="text-sm font-medium">{faq.q}</span>
                  <ChevronDown
                    className={`w-4 h-4 text-white/40 transition-transform ${
                      expandedFaq === index ? "rotate-180" : ""
                    }`}
                  />
                </button>
                <AnimatePresence>
                  {expandedFaq === index && (
                    <motion.p
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: "auto" }}
                      exit={{ opacity: 0, height: 0 }}
                      className="text-sm text-white/60 mt-2"
                    >
                      {faq.a}
                    </motion.p>
                  )}
                </AnimatePresence>
              </div>
            ))}
          </CardContent>
        </Card>
      </motion.div>

      {/* Help Modal */}
      <AnimatePresence>
        {showHelp && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/80 z-50 flex items-center justify-center p-4"
            onClick={() => setShowHelp(false)}
          >
            <motion.div
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
              className="bg-spredd-dark rounded-xl w-full max-w-sm"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between p-4 border-b border-border">
                <h3 className="font-semibold">Get Help</h3>
                <Button variant="ghost" size="icon" onClick={() => setShowHelp(false)}>
                  <X className="w-4 h-4" />
                </Button>
              </div>
              <div className="p-4 space-y-3">
                <Button
                  variant="outline"
                  className="w-full justify-start gap-3"
                  onClick={() => {
                    window.open("https://t.me/spreddmarketsgroup", "_blank");
                    setShowHelp(false);
                  }}
                >
                  <MessageCircle className="w-5 h-5" />
                  <div className="text-left">
                    <p className="font-medium">Telegram Community</p>
                    <p className="text-xs text-white/40">Join our support group</p>
                  </div>
                </Button>
                <Button
                  variant="outline"
                  className="w-full justify-start gap-3"
                  onClick={() => {
                    window.open("https://x.com/spreddterminal", "_blank");
                    setShowHelp(false);
                  }}
                >
                  <ExternalLink className="w-5 h-5" />
                  <div className="text-left">
                    <p className="font-medium">Twitter/X</p>
                    <p className="text-xs text-white/40">@spreddterminal</p>
                  </div>
                </Button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Close Button (for Mini App) */}
      <Button
        variant="outline"
        className="w-full"
        onClick={close}
      >
        Close Mini App
      </Button>
    </div>
  );
}

interface MenuItemProps {
  icon: React.ElementType;
  label: string;
  description: string;
  onClick: () => void;
  expanded?: boolean;
}

function MenuItem({ icon: Icon, label, description, onClick, expanded }: MenuItemProps) {
  return (
    <button
      className="w-full flex items-center gap-3 p-4 hover:bg-white/5 transition-colors text-left"
      onClick={onClick}
    >
      <div className="w-10 h-10 rounded-lg bg-spredd-dark flex items-center justify-center">
        <Icon className="w-5 h-5 text-white/60" />
      </div>
      <div className="flex-1">
        <p className="font-medium">{label}</p>
        <p className="text-xs text-white/40">{description}</p>
      </div>
      {expanded !== undefined ? (
        <ChevronDown className={`w-4 h-4 text-white/40 transition-transform ${expanded ? "rotate-180" : ""}`} />
      ) : (
        <ChevronRight className="w-4 h-4 text-white/40" />
      )}
    </button>
  );
}
