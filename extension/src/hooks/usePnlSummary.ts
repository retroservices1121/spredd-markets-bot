import { useState, useEffect, useCallback } from "react";
import type { PnlSummaryData } from "@/core/markets";
import { getPnlSummary } from "@/lib/messaging";

interface UsePnlSummaryReturn {
  summary: PnlSummaryData | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

/** Validate and normalize PnL data from API */
function normalizePnl(raw: unknown): PnlSummaryData | null {
  if (!raw || typeof raw !== "object") return null;
  const d = raw as Record<string, unknown>;
  // Must have at least one recognizable field
  if (d.total_pnl === undefined && d.total_trades === undefined) return null;
  return {
    platform: String(d.platform ?? "all"),
    total_pnl: Number(d.total_pnl) || 0,
    total_trades: Number(d.total_trades) || 0,
    roi_percent: Number(d.roi_percent) || 0,
    winning_trades: Number(d.winning_trades) || 0,
    losing_trades: Number(d.losing_trades) || 0,
    total_invested: Number(d.total_invested) || 0,
  };
}

export function usePnlSummary(): UsePnlSummaryReturn {
  const [summary, setSummary] = useState<PnlSummaryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getPnlSummary();
      if (res.success && res.data) {
        const normalized = normalizePnl(res.data);
        if (normalized) {
          setSummary(normalized);
        } else {
          setSummary(null);
        }
      } else {
        setError(res.error ?? "Failed to load PnL");
        setSummary(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load PnL");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return { summary, loading, error, refresh: load };
}
