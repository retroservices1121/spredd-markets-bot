import { useState, useCallback } from "react";

export function useLikes() {
  const [liked, setLiked] = useState<Set<string>>(new Set());

  const isLiked = useCallback(
    (platform: string, marketId: string) => liked.has(`${platform}:${marketId}`),
    [liked]
  );

  const toggle = useCallback((platform: string, marketId: string) => {
    const key = `${platform}:${marketId}`;
    setLiked((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
    // TODO: call API when endpoint exists
  }, []);

  return { isLiked, toggle };
}
