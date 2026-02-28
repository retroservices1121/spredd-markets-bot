import { Avatar } from "@/components/ui/avatar";
import { GlassCard } from "@/components/ui/glass-card";
import { Button } from "@/components/ui/button";
import { BottomSheet } from "@/components/ui/bottom-sheet";
import { formatUSD } from "@/lib/utils";

interface UserDetailSheetProps {
  open: boolean;
  onClose: () => void;
  user: {
    username: string;
    avatar?: string;
    pnl?: number;
    win_rate?: number;
    total_trades?: number;
  };
  following?: boolean;
  onFollow?: () => void;
}

export function UserDetailSheet({
  open,
  onClose,
  user,
  following,
  onFollow,
}: UserDetailSheetProps) {
  return (
    <BottomSheet open={open} onClose={onClose}>
      <div className="flex flex-col items-center pb-4">
        <Avatar name={user.username} src={user.avatar} size="xl" />
        <h3 className="text-lg font-bold text-white mt-3">
          {user.username}
        </h3>

        {/* Stats */}
        <div className="grid grid-cols-3 gap-3 w-full mt-4">
          <GlassCard className="text-center py-3">
            <p className="text-lg font-bold text-spredd-green">
              {user.pnl != null ? formatUSD(user.pnl) : "—"}
            </p>
            <p className="text-[10px] text-white/40">Profit</p>
          </GlassCard>
          <GlassCard className="text-center py-3">
            <p className="text-lg font-bold text-white">
              {user.win_rate != null ? `${Math.round(user.win_rate * 100)}%` : "—"}
            </p>
            <p className="text-[10px] text-white/40">Win Rate</p>
          </GlassCard>
          <GlassCard className="text-center py-3">
            <p className="text-lg font-bold text-white">
              {user.total_trades ?? "—"}
            </p>
            <p className="text-[10px] text-white/40">Trades</p>
          </GlassCard>
        </div>

        {/* Follow button */}
        {onFollow && (
          <Button
            variant={following ? "outline" : "default"}
            className="w-full mt-4"
            onClick={onFollow}
          >
            {following ? "Unfollow" : "Follow"}
          </Button>
        )}
      </div>
    </BottomSheet>
  );
}
