import { useState, useEffect, useCallback } from "react";
import { getLeaderboard, type LeaderboardEntry } from "@/api/client";

type Period = "24h" | "7d" | "30d" | "all";
type SortBy = "profit" | "win_rate";

interface UseRankingReturn {
  entries: LeaderboardEntry[];
  loading: boolean;
  period: Period;
  sortBy: SortBy;
  setPeriod: (p: Period) => void;
  setSortBy: (s: SortBy) => void;
}

export function useRanking(): UseRankingReturn {
  const [entries, setEntries] = useState<LeaderboardEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [period, setPeriod] = useState<Period>("7d");
  const [sortBy, setSortBy] = useState<SortBy>("profit");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getLeaderboard(period, sortBy);
      setEntries(res.entries);
    } catch {
      setEntries([]);
    } finally {
      setLoading(false);
    }
  }, [period, sortBy]);

  useEffect(() => {
    load();
  }, [load]);

  return { entries, loading, period, sortBy, setPeriod, setSortBy };
}
