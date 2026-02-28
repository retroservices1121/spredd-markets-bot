import { Trophy, Loader2 } from "lucide-react";
import { Avatar } from "@/components/ui/avatar";
import { GlassCard } from "@/components/ui/glass-card";
import { useRanking } from "@/hooks/useRanking";
import { formatUSD, cn } from "@/lib/utils";

const PERIODS = [
  { id: "24h" as const, label: "24H" },
  { id: "7d" as const, label: "7D" },
  { id: "30d" as const, label: "30D" },
  { id: "all" as const, label: "All" },
];

const SORTS = [
  { id: "profit" as const, label: "Profit" },
  { id: "win_rate" as const, label: "Win Rate" },
];

const podiumColors = ["text-yellow-400", "text-gray-300", "text-amber-600"];
const podiumBg = ["bg-yellow-400/10", "bg-gray-300/10", "bg-amber-600/10"];

export function RankingPage() {
  const { entries, loading, period, sortBy, setPeriod, setSortBy } = useRanking();

  const top3 = entries.slice(0, 3);
  const rest = entries.slice(3);

  return (
    <div className="min-h-[100dvh] bg-spredd-bg pb-24">
      {/* Header */}
      <div className="sticky top-0 z-30 glass-tab-bar px-5 pt-14 pb-3">
        <h1 className="text-lg font-bold text-white mb-3">Leaderboard</h1>

        {/* Filter bar */}
        <div className="flex items-center justify-between">
          <div className="flex gap-1">
            {PERIODS.map((p) => (
              <button
                key={p.id}
                onClick={() => setPeriod(p.id)}
                className={cn(
                  "px-3 py-1 rounded-full text-xs font-medium transition-all",
                  period === p.id
                    ? "bg-spredd-green/20 text-spredd-green"
                    : "text-white/40 hover:text-white/60"
                )}
              >
                {p.label}
              </button>
            ))}
          </div>
          <div className="flex gap-1">
            {SORTS.map((s) => (
              <button
                key={s.id}
                onClick={() => setSortBy(s.id)}
                className={cn(
                  "px-3 py-1 rounded-full text-xs font-medium transition-all",
                  sortBy === s.id
                    ? "bg-white/10 text-white"
                    : "text-white/40 hover:text-white/60"
                )}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {loading && (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="w-8 h-8 animate-spin text-spredd-green" />
        </div>
      )}

      {!loading && (
        <div className="px-5 pt-4 space-y-4">
          {/* Podium — top 3 */}
          {top3.length > 0 && (
            <div className="flex items-end justify-center gap-3 pb-4">
              {/* 2nd place */}
              {top3[1] && (
                <div className="flex flex-col items-center w-1/3">
                  <div className={cn("w-14 h-14 rounded-full flex items-center justify-center mb-2", podiumBg[1])}>
                    <Avatar name={top3[1].username} size="lg" />
                  </div>
                  <span className="text-xs font-medium text-white truncate max-w-full">
                    {top3[1].username}
                  </span>
                  <span className={cn("text-sm font-bold mt-1", podiumColors[1])}>
                    {formatUSD(top3[1].pnl)}
                  </span>
                  <Trophy size={16} className={cn("mt-1", podiumColors[1])} />
                </div>
              )}

              {/* 1st place */}
              {top3[0] && (
                <div className="flex flex-col items-center w-1/3 -mt-4">
                  <div className={cn("w-18 h-18 rounded-full flex items-center justify-center mb-2 ring-2 ring-yellow-400/30", podiumBg[0])}>
                    <Avatar name={top3[0].username} size="xl" />
                  </div>
                  <span className="text-sm font-bold text-white truncate max-w-full">
                    {top3[0].username}
                  </span>
                  <span className={cn("text-lg font-bold mt-1", podiumColors[0])}>
                    {formatUSD(top3[0].pnl)}
                  </span>
                  <Trophy size={20} className={cn("mt-1", podiumColors[0])} />
                </div>
              )}

              {/* 3rd place */}
              {top3[2] && (
                <div className="flex flex-col items-center w-1/3">
                  <div className={cn("w-14 h-14 rounded-full flex items-center justify-center mb-2", podiumBg[2])}>
                    <Avatar name={top3[2].username} size="lg" />
                  </div>
                  <span className="text-xs font-medium text-white truncate max-w-full">
                    {top3[2].username}
                  </span>
                  <span className={cn("text-sm font-bold mt-1", podiumColors[2])}>
                    {formatUSD(top3[2].pnl)}
                  </span>
                  <Trophy size={16} className={cn("mt-1", podiumColors[2])} />
                </div>
              )}
            </div>
          )}

          {/* Ranked list */}
          <div className="space-y-2">
            {rest.map((entry) => (
              <GlassCard key={entry.user_id} className="flex items-center gap-3">
                <span className="text-sm font-bold text-white/30 w-6 text-center shrink-0">
                  {entry.rank}
                </span>
                <Avatar name={entry.username} size="sm" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-white truncate">
                    {entry.username}
                  </p>
                  <p className="text-[10px] text-white/40">
                    {entry.total_trades} trades · {Math.round(entry.win_rate * 100)}% win
                  </p>
                </div>
                <span className="text-sm font-bold text-spredd-green shrink-0">
                  {formatUSD(entry.pnl)}
                </span>
              </GlassCard>
            ))}
          </div>

          {entries.length === 0 && (
            <div className="text-center py-12">
              <p className="text-white/40 text-sm">No leaderboard data yet</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
