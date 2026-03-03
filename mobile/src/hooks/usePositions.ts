import { useState, useEffect, useCallback } from "react";
import { getPositions, type Position } from "@/api/client";

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
      const res = await getPositions(filter === "all" ? undefined : filter);
      setPositions(res.positions || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load positions");
      setPositions([]);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    load();
  }, [load]);

  return { positions, loading, error, filter, setFilter, refresh: load };
}
