import { useState, useEffect, useCallback } from "react";
import type { Position, Platform } from "@/core/markets";
import { getPositions } from "@/lib/messaging";

export type PositionFilter = "open" | "closed" | "all";

interface UsePositionsReturn {
  positions: Position[];
  loading: boolean;
  error: string | null;
  filter: PositionFilter;
  setFilter: (f: PositionFilter) => void;
  refresh: () => void;
}

/** Validate and normalize a single position from API */
function normalizePosition(raw: unknown): Position | null {
  if (!raw || typeof raw !== "object") return null;
  const d = raw as Record<string, unknown>;
  if (!d.id && !d.market_id) return null;
  return {
    id: String(d.id ?? d.market_id ?? ""),
    platform: (d.platform as Platform) ?? "polymarket",
    market_id: String(d.market_id ?? ""),
    market_title: String(d.market_title ?? d.title ?? "Unknown Market"),
    outcome: String(d.outcome ?? "Yes"),
    token_amount: Number(d.token_amount ?? d.amount ?? 0) || 0,
    entry_price: Number(d.entry_price ?? d.avg_price ?? 0) || 0,
    current_price: Number(d.current_price ?? 0) || 0,
    status: (d.status as Position["status"]) ?? "open",
    pnl: Number(d.pnl ?? d.profit ?? 0) || 0,
    created_at: String(d.created_at ?? ""),
  };
}

export function usePositions(): UsePositionsReturn {
  const [positions, setPositions] = useState<Position[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<PositionFilter>("open");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getPositions({
        status: filter === "all" ? undefined : filter,
      });
      if (res.success && res.data) {
        const arr = Array.isArray(res.data) ? res.data : [];
        const normalized = arr
          .map(normalizePosition)
          .filter((p): p is Position => p !== null);
        setPositions(normalized);
      } else {
        setError(res.error ?? "Failed to load positions");
        setPositions([]);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load positions");
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    load();
  }, [load]);

  return { positions, loading, error, filter, setFilter, refresh: load };
}
