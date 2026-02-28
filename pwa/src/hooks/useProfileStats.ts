import { useState, useEffect, useCallback } from "react";
import {
  getUserInfo,
  getBalances,
  getPositions,
  getPnlSummary,
  type UserInfo,
  type WalletBalance,
  type Position,
  type PnlSummary,
} from "@/api/client";

interface UseProfileStatsReturn {
  user: UserInfo | null;
  balances: WalletBalance[];
  positions: Position[];
  pnl: PnlSummary | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

const DEFAULT_PNL: PnlSummary = {
  total_pnl: 0,
  win_rate: 0,
  active_positions: 0,
  win_streak: 0,
  total_trades: 0,
  total_invested: 0,
};

export function useProfileStats(): UseProfileStatsReturn {
  const [user, setUser] = useState<UserInfo | null>(null);
  const [balances, setBalances] = useState<WalletBalance[]>([]);
  const [positions, setPositions] = useState<Position[]>([]);
  const [pnl, setPnl] = useState<PnlSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);

    const [userRes, balRes, posRes, pnlRes] = await Promise.allSettled([
      getUserInfo(),
      getBalances(),
      getPositions("open"),
      getPnlSummary(),
    ]);

    if (userRes.status === "fulfilled") setUser(userRes.value);
    if (balRes.status === "fulfilled") setBalances(balRes.value.balances || []);
    if (posRes.status === "fulfilled") setPositions(posRes.value.positions || []);
    if (pnlRes.status === "fulfilled") setPnl(pnlRes.value);
    else setPnl(DEFAULT_PNL);

    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return { user, balances, positions, pnl, loading, error, refresh: load };
}
