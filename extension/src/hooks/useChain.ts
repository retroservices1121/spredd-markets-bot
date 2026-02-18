import { useState, useEffect, useCallback } from "react";
import type { ChainId, Preferences } from "@/core/types";
import { CHAINS, ALL_CHAIN_IDS } from "@/core/chains";

export function useChain() {
  const [selected, setSelected] = useState<ChainId | "all">("all");

  useEffect(() => {
    chrome.storage.local.get("preferences").then((result) => {
      const prefs = result.preferences as Preferences | undefined;
      if (prefs?.selectedChain) {
        setSelected(prefs.selectedChain);
      }
    });
  }, []);

  const selectChain = useCallback((chain: ChainId | "all") => {
    setSelected(chain);
    chrome.storage.local.get("preferences").then((result) => {
      const current = (result.preferences as Preferences) || {
        selectedChain: "all",
        autoLockMinutes: 15,
      };
      chrome.storage.local.set({
        preferences: { ...current, selectedChain: chain },
      });
    });
  }, []);

  const chain = selected === "all" ? null : CHAINS[selected];
  const allChains = ALL_CHAIN_IDS.map((id) => CHAINS[id]);

  return { selected, selectChain, chain, allChains };
}
