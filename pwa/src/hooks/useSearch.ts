import { useState, useCallback, useEffect, useRef } from "react";
import { searchMarkets, type FeedMarket } from "@/api/client";

const STORAGE_KEY = "spredd_recent_searches";
const MAX_RECENT = 8;

interface UseSearchReturn {
  query: string;
  setQuery: (q: string) => void;
  results: FeedMarket[];
  loading: boolean;
  recentSearches: string[];
  addRecentSearch: (q: string) => void;
  clearRecent: () => void;
}

export function useSearch(): UseSearchReturn {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<FeedMarket[]>([]);
  const [loading, setLoading] = useState(false);
  const [recentSearches, setRecentSearches] = useState<string[]>(() => {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
    } catch {
      return [];
    }
  });
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  const addRecentSearch = useCallback((q: string) => {
    if (!q.trim()) return;
    setRecentSearches((prev) => {
      const next = [q, ...prev.filter((s) => s !== q)].slice(0, MAX_RECENT);
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      return next;
    });
  }, []);

  const clearRecent = useCallback(() => {
    setRecentSearches([]);
    localStorage.removeItem(STORAGE_KEY);
  }, []);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);

    if (!query.trim()) {
      setResults([]);
      setLoading(false);
      return;
    }

    setLoading(true);
    debounceRef.current = setTimeout(async () => {
      try {
        const res = await searchMarkets(query);
        setResults(res.markets || []);
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 400);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query]);

  return { query, setQuery, results, loading, recentSearches, addRecentSearch, clearRecent };
}
