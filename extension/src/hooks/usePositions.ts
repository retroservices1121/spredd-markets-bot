import { useState, useEffect, useCallback } from "react";
import type { Position } from "@/core/markets";
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
        setPositions(Array.isArray(res.data) ? res.data : []);
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
