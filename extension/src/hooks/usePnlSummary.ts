import { useState, useEffect, useCallback } from "react";
import type { PnlSummaryData } from "@/core/markets";
import { getPnlSummary } from "@/lib/messaging";

interface UsePnlSummaryReturn {
  summary: PnlSummaryData | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
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
        setSummary(res.data);
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
