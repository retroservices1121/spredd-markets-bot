import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Lock, Key, Plus, Loader2 } from "lucide-react";
import { getAutoLock, setAutoLock } from "@/lib/messaging";
import { decryptVault, encryptVault } from "@/core/vault";
import type { DecryptedVault, VaultMeta } from "@/core/types";

interface SettingsPageProps {
  onLock: () => void;
  vault?: DecryptedVault | null;
  onVaultUpdated?: () => void;
}

const TIMEOUT_OPTIONS = [
  { label: "5 min", value: 5 },
  { label: "15 min", value: 15 },
  { label: "30 min", value: 30 },
  { label: "60 min", value: 60 },
];

export function SettingsPage({ onLock, vault, onVaultUpdated }: SettingsPageProps) {
  const [autoLockMinutes, setAutoLockMinutes] = useState(15);
  const [showExport, setShowExport] = useState(false);
  const [exportPassword, setExportPassword] = useState("");
  const [exportData, setExportData] = useState<string | null>(null);
  const [exportError, setExportError] = useState("");
  const [exportLoading, setExportLoading] = useState(false);

  // Import key state
  const [showImportKey, setShowImportKey] = useState<"evm" | "solana" | null>(null);
  const [importKeyValue, setImportKeyValue] = useState("");
  const [importPassword, setImportPassword] = useState("");
  const [importError, setImportError] = useState("");
  const [importLoading, setImportLoading] = useState(false);

  const missingEvm = vault && !vault.evmAddress;
  const missingSolana = vault && !vault.solanaAddress;

  useEffect(() => {
    getAutoLock().then((res) => {
      if (res.success && res.data) {
        setAutoLockMinutes(res.data.minutes);
      }
    });
  }, []);

  async function handleAutoLockChange(minutes: number) {
    setAutoLockMinutes(minutes);
    await setAutoLock(minutes);
  }

  async function handleExport() {
    setExportLoading(true);
    setExportError("");
    try {
      const result = await chrome.storage.local.get("vault_encrypted");
      if (!result.vault_encrypted) {
        setExportError("No vault found");
        return;
      }
      const json = await decryptVault(result.vault_encrypted, exportPassword);
      const v = JSON.parse(json) as DecryptedVault;
      if (v.mnemonic) {
        setExportData(v.mnemonic);
      } else {
        setExportData(
          v.evmPrivateKey || v.solanaPrivateKey || "No keys found"
        );
      }
    } catch {
      setExportError("Wrong password");
    } finally {
      setExportLoading(false);
    }
  }

  async function handleImportKey() {
    if (!showImportKey) return;
    setImportLoading(true);
    setImportError("");

    try {
      // Decrypt existing vault
      const stored = await chrome.storage.local.get("vault_encrypted");
      if (!stored.vault_encrypted) {
        setImportError("No vault found");
        return;
      }
      const json = await decryptVault(stored.vault_encrypted, importPassword);
      const existing = JSON.parse(json) as DecryptedVault;

      const keyTrimmed = importKeyValue.trim();

      if (showImportKey === "evm") {
        if (!/^(0x)?[0-9a-fA-F]{64}$/.test(keyTrimmed)) {
          setImportError("Invalid EVM private key");
          return;
        }
        const { Wallet } = await import("ethers");
        const wallet = new Wallet(
          keyTrimmed.startsWith("0x") ? keyTrimmed : `0x${keyTrimmed}`
        );
        existing.evmPrivateKey = wallet.privateKey;
        existing.evmAddress = wallet.address;
      } else {
        if (!/^[1-9A-HJ-NP-Za-km-z]{64,88}$/.test(keyTrimmed)) {
          setImportError("Invalid Solana private key");
          return;
        }
        const { Keypair } = await import("@solana/web3.js");
        const bs58 = (await import("bs58")).default;
        const decoded = bs58.decode(keyTrimmed);
        const keypair = Keypair.fromSecretKey(decoded);
        existing.solanaPrivateKey = bs58.encode(keypair.secretKey);
        existing.solanaAddress = keypair.publicKey.toBase58();
      }

      // Re-encrypt and store
      const encrypted = await encryptVault(JSON.stringify(existing), importPassword);
      const meta: VaultMeta = {
        version: 1,
        createdAt: Date.now(),
        evmAddress: existing.evmAddress,
        solanaAddress: existing.solanaAddress,
      };
      await chrome.storage.local.set({
        vault_encrypted: encrypted,
        vault_meta: meta,
      });

      // Re-unlock with updated vault
      await chrome.runtime.sendMessage({
        type: "UNLOCK_VAULT",
        payload: { password: importPassword },
      });

      setShowImportKey(null);
      setImportKeyValue("");
      setImportPassword("");
      onVaultUpdated?.();
    } catch {
      setImportError("Wrong password or invalid key");
    } finally {
      setImportLoading(false);
    }
  }

  return (
    <div className="p-4 space-y-6">
      {/* Import missing key */}
      {(missingEvm || missingSolana) && (
        <div>
          <h3 className="text-sm font-medium text-foreground mb-2">
            Add Wallet
          </h3>
          {showImportKey ? (
            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">
                Import {showImportKey === "evm" ? "EVM" : "Solana"} private key
              </p>
              <input
                value={importKeyValue}
                onChange={(e) => { setImportKeyValue(e.target.value); setImportError(""); }}
                placeholder={showImportKey === "evm" ? "0x... (hex private key)" : "Base58-encoded key"}
                className="w-full px-3 py-2 rounded-lg bg-secondary border border-input text-xs font-mono text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                autoFocus
              />
              <Input
                type="password"
                value={importPassword}
                onChange={(e) => { setImportPassword(e.target.value); setImportError(""); }}
                placeholder="Enter wallet password to confirm"
              />
              {importError && <p className="text-xs text-spredd-red">{importError}</p>}
              <div className="flex gap-2">
                <Button
                  size="sm"
                  disabled={!importKeyValue.trim() || !importPassword || importLoading}
                  onClick={handleImportKey}
                >
                  {importLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : "Import"}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setShowImportKey(null);
                    setImportKeyValue("");
                    setImportPassword("");
                    setImportError("");
                  }}
                >
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              {missingSolana && (
                <Button
                  variant="secondary"
                  className="w-full justify-start"
                  onClick={() => setShowImportKey("solana")}
                >
                  <Plus className="w-4 h-4" />
                  Import Solana Key
                </Button>
              )}
              {missingEvm && (
                <Button
                  variant="secondary"
                  className="w-full justify-start"
                  onClick={() => setShowImportKey("evm")}
                >
                  <Plus className="w-4 h-4" />
                  Import EVM Key
                </Button>
              )}
            </div>
          )}
        </div>
      )}

      {/* Auto-lock timeout */}
      <div>
        <h3 className="text-sm font-medium text-foreground mb-2">
          Auto-Lock Timeout
        </h3>
        <div className="grid grid-cols-4 gap-2">
          {TIMEOUT_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              onClick={() => handleAutoLockChange(opt.value)}
              className={`px-3 py-2 rounded-lg text-xs font-medium transition-colors ${
                autoLockMinutes === opt.value
                  ? "bg-spredd-orange text-white"
                  : "bg-secondary text-muted-foreground hover:text-foreground"
              }`}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Lock now */}
      <div>
        <Button variant="outline" className="w-full" onClick={onLock}>
          <Lock className="w-4 h-4" />
          Lock Now
        </Button>
      </div>

      {/* Export seed phrase */}
      <div>
        <h3 className="text-sm font-medium text-foreground mb-2">
          Export Seed Phrase
        </h3>
        {!showExport ? (
          <Button
            variant="secondary"
            className="w-full"
            onClick={() => setShowExport(true)}
          >
            <Key className="w-4 h-4" />
            Show Seed Phrase
          </Button>
        ) : exportData ? (
          <div className="p-3 rounded-lg bg-secondary border border-border">
            <p className="text-xs text-muted-foreground mb-2">
              Your seed phrase:
            </p>
            <p className="text-sm font-mono text-foreground break-all select-all">
              {exportData}
            </p>
            <Button
              variant="ghost"
              size="sm"
              className="mt-2"
              onClick={() => {
                setExportData(null);
                setShowExport(false);
                setExportPassword("");
              }}
            >
              Hide
            </Button>
          </div>
        ) : (
          <div className="space-y-2">
            <Input
              type="password"
              value={exportPassword}
              onChange={(e) => {
                setExportPassword(e.target.value);
                setExportError("");
              }}
              placeholder="Enter password to decrypt"
            />
            {exportError && (
              <p className="text-xs text-spredd-red">{exportError}</p>
            )}
            <div className="flex gap-2">
              <Button
                size="sm"
                disabled={!exportPassword || exportLoading}
                onClick={handleExport}
              >
                {exportLoading ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  "Decrypt"
                )}
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setShowExport(false);
                  setExportPassword("");
                  setExportError("");
                }}
              >
                Cancel
              </Button>
            </div>
          </div>
        )}
      </div>

      {/* Version */}
      <div className="text-center">
        <p className="text-xs text-muted-foreground">Spredd Markets v0.2.0</p>
      </div>
    </div>
  );
}
