import { useState, useEffect, useCallback } from "react";
import {
  getSession,
  unlockVault as sendUnlock,
  lockVault as sendLock,
  getVaultData as sendGetVaultData,
} from "@/lib/messaging";
import type { DecryptedVault, VaultMeta } from "@/core/types";

export type VaultState = "loading" | "no_vault" | "locked" | "unlocked";

export function useVault() {
  const [state, setState] = useState<VaultState>("loading");
  const [vaultData, setVaultData] = useState<DecryptedVault | null>(null);
  const [vaultMeta, setVaultMeta] = useState<VaultMeta | null>(null);
  const [error, setError] = useState<string | null>(null);

  const checkSession = useCallback(async () => {
    const res = await getSession();
    if (!res.success) {
      setState("no_vault");
      return;
    }
    const { hasVault, unlocked } = res.data!;
    if (!hasVault) {
      setState("no_vault");
    } else if (unlocked) {
      // Fetch vault data
      const vaultRes = await sendGetVaultData();
      if (vaultRes.success && vaultRes.data) {
        setVaultData(vaultRes.data as DecryptedVault);
      }
      // Fetch meta
      const metaResult = await chrome.storage.local.get("vault_meta");
      if (metaResult.vault_meta) {
        setVaultMeta(metaResult.vault_meta as VaultMeta);
      }
      setState("unlocked");
    } else {
      setState("locked");
    }
  }, []);

  useEffect(() => {
    checkSession();
  }, [checkSession]);

  const unlock = useCallback(async (password: string) => {
    setError(null);
    const res = await sendUnlock(password);
    if (res.success) {
      await checkSession();
      return true;
    }
    setError(res.error ?? "Unlock failed");
    return false;
  }, [checkSession]);

  const lock = useCallback(async () => {
    await sendLock();
    setVaultData(null);
    setState("locked");
  }, []);

  const refresh = useCallback(() => {
    checkSession();
  }, [checkSession]);

  return { state, vaultData, vaultMeta, error, unlock, lock, refresh };
}
