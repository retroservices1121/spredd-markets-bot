import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Lock, Key, Loader2 } from "lucide-react";
import { getAutoLock, setAutoLock } from "@/lib/messaging";
import { decryptVault } from "@/core/vault";
import type { DecryptedVault } from "@/core/types";

interface SettingsPageProps {
  onLock: () => void;
}

const TIMEOUT_OPTIONS = [
  { label: "5 min", value: 5 },
  { label: "15 min", value: 15 },
  { label: "30 min", value: 30 },
  { label: "60 min", value: 60 },
];

export function SettingsPage({ onLock }: SettingsPageProps) {
  const [autoLockMinutes, setAutoLockMinutes] = useState(15);
  const [showExport, setShowExport] = useState(false);
  const [exportPassword, setExportPassword] = useState("");
  const [exportData, setExportData] = useState<string | null>(null);
  const [exportError, setExportError] = useState("");
  const [exportLoading, setExportLoading] = useState(false);

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
      const vault = JSON.parse(json) as DecryptedVault;
      if (vault.mnemonic) {
        setExportData(vault.mnemonic);
      } else {
        setExportData(
          vault.evmPrivateKey || vault.solanaPrivateKey || "No keys found"
        );
      }
    } catch {
      setExportError("Wrong password");
    } finally {
      setExportLoading(false);
    }
  }

  return (
    <div className="p-4 space-y-6">
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
        <p className="text-xs text-muted-foreground">Spredd Wallet v0.1.0</p>
      </div>
    </div>
  );
}
