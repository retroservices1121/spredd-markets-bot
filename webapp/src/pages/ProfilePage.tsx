import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import {
  User,
  Share2,
  Copy,
  ChevronRight,
  Settings,
  HelpCircle,
  ExternalLink,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useTelegram } from "@/contexts/TelegramContext";
import { getCurrentUser, getReferralStats } from "@/lib/api";
import { formatUSD, getPlatformName } from "@/lib/utils";
import { toast } from "sonner";

export default function ProfilePage() {
  const { user: tgUser, initData, hapticFeedback, close } = useTelegram();

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
              icon={Settings}
              label="Settings"
              description="Slippage, notifications"
              onClick={() => toast.info("Use the bot for settings")}
            />
            <MenuItem
              icon={HelpCircle}
              label="Help & FAQ"
              description="Get support"
              onClick={() => window.open("https://t.me/spreddmarketsgroup", "_blank")}
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
}

function MenuItem({ icon: Icon, label, description, onClick }: MenuItemProps) {
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
      <ChevronRight className="w-4 h-4 text-white/40" />
    </button>
  );
}
