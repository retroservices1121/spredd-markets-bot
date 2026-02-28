import { useState, useCallback } from "react";
import { toggleBookmark } from "@/api/client";

export function useBookmarks() {
  const [bookmarked, setBookmarked] = useState<Set<string>>(new Set());

  const isBookmarked = useCallback(
    (platform: string, marketId: string) => bookmarked.has(`${platform}:${marketId}`),
    [bookmarked]
  );

  const toggle = useCallback(async (platform: string, marketId: string) => {
    const key = `${platform}:${marketId}`;

    // Optimistic update
    setBookmarked((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

    try {
      await toggleBookmark(platform, marketId);
    } catch {
      // Revert on failure
      setBookmarked((prev) => {
        const next = new Set(prev);
        if (next.has(key)) next.delete(key);
        else next.add(key);
        return next;
      });
    }
  }, []);

  return { isBookmarked, toggle };
}
